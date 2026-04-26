#!/usr/bin/env python3
"""Local E2E exercise for Poker44 dev validator/miner competition flow.

This script assumes a local backend dev instance is already running and serving:
  - eval current chunk on localhost
  - competition endpoints on localhost

It does not touch main/prod. It seeds signed validator reports against the local
backend using deterministic test hotkeys and verifies the API-side flow:
  - fetch active eval chunk
  - score it with two synthetic miners
  - report scores from two synthetic validators
  - publish a network snapshot for leaderboard visibility
  - query current competition state / leaderboard / settlement weights
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import bittensor as bt
import numpy as np

from neurons.miner import Miner
from poker44.score.scoring import reward
from poker44.utils.model_manifest import build_local_model_manifest, manifest_digest
from poker44.utils.runtime_info import build_signed_runtime_request, post_runtime_snapshot
from poker44.validator.synapse import DetectionSynapse


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_BASE_URL = os.getenv("POKER44_LOCAL_E2E_BACKEND_BASE_URL", "http://127.0.0.1:3101")
EVAL_SECRET = os.getenv("POKER44_LOCAL_E2E_SECRET", "local-e2e-secret")
NETUID = 126
BURN_UID = 0


@dataclass
class WalletShim:
    hotkey: Any


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    req_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        req_headers.setdefault("content-type", "application/json")
    request = Request(url, data=data, method=method, headers=req_headers)
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _current_competition_epoch() -> dict[str, Any]:
    response = _http_json(urljoin(BACKEND_BASE_URL, "/api/v1/competition/current"))
    return dict(response["data"]["epoch"])


def _previous_epoch_from(current_epoch: dict[str, Any]) -> dict[str, str]:
    start = datetime.fromisoformat(current_epoch["startsAt"].replace("Z", "+00:00"))
    prev_start = start - timedelta(days=7)
    prev_end = start
    return {
        "epochId": f"week_{prev_start.date().isoformat()}_2000utc",
        "startsAt": prev_start.isoformat().replace("+00:00", "Z"),
        "endsAt": prev_end.isoformat().replace("+00:00", "Z"),
    }


def _fetch_active_chunk() -> dict[str, Any]:
    response = _http_json(
        urljoin(BACKEND_BASE_URL, "/internal/eval/current"),
        headers={"x-eval-secret": EVAL_SECRET},
    )
    payload = response["data"]
    if not payload.get("active"):
        raise RuntimeError("Expected an active local eval chunk")
    return payload


def _build_manifest(name: str, version: str, repo_commit: str) -> dict[str, Any]:
    manifest = build_local_model_manifest(
        repo_root=REPO_ROOT,
        implementation_files=[REPO_ROOT / "neurons" / "miner.py"],
        defaults={
            "model_name": name,
            "model_version": version,
            "framework": "python-heuristic",
            "license": "MIT",
            "repo_url": "https://github.com/Poker44/Poker44-subnet",
            "repo_commit": repo_commit,
            "notes": f"Local E2E manifest for {name}",
            "open_source": True,
            "inference_mode": "remote",
            "training_data_statement": "Local deterministic E2E scorer using eval batches.",
            "training_data_sources": ["local-e2e"],
            "private_data_attestation": "No validator-only data used outside the provided batch.",
        },
    )
    return manifest


def _score_batches(batches: list[dict[str, Any]], mode: str) -> list[float]:
    scores: list[float] = []
    for batch in batches:
        base = Miner.score_chunk(batch.get("hands") or [])
        if mode == "heuristic":
            score = base
        elif mode == "inverse":
            score = 1.0 - base
        elif mode == "softened":
            score = min(1.0, max(0.0, 0.05 + 0.9 * base))
        elif mode == "degraded":
            score = min(1.0, max(0.0, 0.95 - 0.9 * base))
        else:
            raise ValueError(f"Unsupported scoring mode: {mode}")
        scores.append(round(float(score), 6))
    return scores


def _labels_from_batches(batches: list[dict[str, Any]]) -> np.ndarray:
    labels = [1 if bool(batch.get("is_bot")) else 0 for batch in batches]
    return np.asarray(labels, dtype=bool)


def _competition_row(
    *,
    uid: int,
    hotkey: str,
    manifest: dict[str, Any],
    scores: list[float],
    labels: np.ndarray,
    latency_seconds: float,
) -> dict[str, Any]:
    rew, metric = reward(np.asarray(scores, dtype=float), labels)
    return {
        "uid": uid,
        "hotkey": hotkey,
        "manifest_digest": manifest_digest(manifest),
        "implementation_sha256": manifest.get("implementation_sha256"),
        "model_name": manifest.get("model_name"),
        "model_version": manifest.get("model_version"),
        "repo_url": manifest.get("repo_url"),
        "repo_commit": manifest.get("repo_commit"),
        "open_source": manifest.get("open_source"),
        "reward": float(rew),
        "ap_score": float(metric["ap_score"]),
        "bot_recall": float(metric["bot_recall"]),
        "human_safety_penalty": float(metric["human_safety_penalty"]),
        "coverage_rate": 1.0,
        "latency_mean_seconds": latency_seconds,
        "sample_count": int(len(scores)),
    }


def _post_signed(url: str, wallet: WalletShim, payload: dict[str, Any]) -> tuple[bool, str]:
    signed = build_signed_runtime_request(wallet=wallet, url=url, payload=payload)
    return post_runtime_snapshot(url=url, payload=payload, timeout_seconds=10, **signed)


def main() -> int:
    current_epoch = _current_competition_epoch()
    previous_epoch = _previous_epoch_from(current_epoch)
    active_chunk = _fetch_active_chunk()
    batches = list(active_chunk["batches"])
    labels = _labels_from_batches(batches)

    validator_a = WalletShim(bt.Keypair.create_from_uri("//Alice"))
    validator_b = WalletShim(bt.Keypair.create_from_uri("//Bob"))
    miner_a = bt.Keypair.create_from_uri("//Charlie")
    miner_b = bt.Keypair.create_from_uri("//Dave")

    manifest_a = _build_manifest("poker44-e2e-heuristic", "1.0.0", "e2eheuristic001")
    manifest_b = _build_manifest("poker44-e2e-inverse", "1.0.0", "e2einverse001")

    miner_a_scores_v1 = _score_batches(batches, "heuristic")
    miner_b_scores_v1 = _score_batches(batches, "inverse")
    miner_a_scores_v2 = _score_batches(batches, "softened")
    miner_b_scores_v2 = _score_batches(batches, "degraded")

    previous_window_end = datetime.fromisoformat(current_epoch["startsAt"].replace("Z", "+00:00"))
    previous_window_start = previous_window_end - timedelta(hours=2)

    report_rows_v1 = [
        _competition_row(
            uid=101,
            hotkey=miner_a.ss58_address,
            manifest=manifest_a,
            scores=miner_a_scores_v1,
            labels=labels,
            latency_seconds=0.42,
        ),
        _competition_row(
            uid=102,
            hotkey=miner_b.ss58_address,
            manifest=manifest_b,
            scores=miner_b_scores_v1,
            labels=labels,
            latency_seconds=0.71,
        ),
    ]
    report_rows_v2 = [
        _competition_row(
            uid=101,
            hotkey=miner_a.ss58_address,
            manifest=manifest_a,
            scores=miner_a_scores_v2,
            labels=labels,
            latency_seconds=0.39,
        ),
        _competition_row(
            uid=102,
            hotkey=miner_b.ss58_address,
            manifest=manifest_b,
            scores=miner_b_scores_v2,
            labels=labels,
            latency_seconds=0.83,
        ),
    ]

    report_url = urljoin(BACKEND_BASE_URL, "/internal/competition/report-scores")
    network_snapshot_url = urljoin(BACKEND_BASE_URL, "/internal/network/snapshots")

    prev_payload_v1 = {
        "hotkey": validator_a.hotkey.ss58_address,
        "validator_uid": 74,
        "competition_epoch_id": previous_epoch["epochId"],
        "competition_epoch_start": previous_epoch["startsAt"],
        "competition_epoch_end": previous_epoch["endsAt"],
        "active_chunk_id": "prev-e2e-chunk-001",
        "active_chunk_hash": "prev-e2e-hash-001",
        "active_window_start": previous_window_start.isoformat().replace("+00:00", "Z"),
        "active_window_end": previous_window_end.isoformat().replace("+00:00", "Z"),
        "competition_scores": report_rows_v1,
    }
    prev_payload_v2 = {
        **prev_payload_v1,
        "hotkey": validator_b.hotkey.ss58_address,
        "validator_uid": 75,
        "competition_scores": report_rows_v2,
    }

    current_payload_v1 = {
        "hotkey": validator_a.hotkey.ss58_address,
        "validator_uid": 74,
        "competition_epoch_id": current_epoch["epochId"],
        "competition_epoch_start": current_epoch["startsAt"],
        "competition_epoch_end": current_epoch["endsAt"],
        "active_chunk_id": active_chunk["chunkId"],
        "active_chunk_hash": active_chunk["chunkHash"],
        "active_window_start": active_chunk["windowStart"],
        "active_window_end": active_chunk["windowEnd"],
        "competition_scores": report_rows_v1,
    }
    current_payload_v2 = {
        **current_payload_v1,
        "hotkey": validator_b.hotkey.ss58_address,
        "validator_uid": 75,
        "competition_scores": report_rows_v2,
    }

    network_snapshot = {
        "status": "running",
        "hotkey": validator_a.hotkey.ss58_address,
        "validator_uid": 74,
        "version": "0.1.10-dev",
        "deploy_version": "0.1.10-dev",
        "netuid": NETUID,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime": {
            "mode": "local-e2e",
            "purpose": "validator-miner-pipeline",
        },
        "subnet": {
            "netuid": NETUID,
            "block_number": 1000001,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "total_neurons": 5,
            "active_neurons": 5,
            "validators_with_permit": 2,
            "active_validators": 2,
            "active_miners": 2,
            "burn_uid": BURN_UID,
            "incentive_burn": "0.97",
        },
        "neurons": [
            {
                "uid": 0,
                "hotkey": "burn",
                "active": True,
                "validator_permit": False,
                "updated_blocks": 0,
                "rank": 0.0,
                "emission": "97",
                "incentive": "0.97",
                "dividends": "0",
                "validator_trust": "0",
                "consensus": "0",
                "total_alpha_stake": "0",
                "stake": "0",
                "axon": {"ip": None, "port": None},
            },
            {
                "uid": 74,
                "hotkey": validator_a.hotkey.ss58_address,
                "active": True,
                "validator_permit": True,
                "updated_blocks": 2,
                "rank": 0.9,
                "emission": "1",
                "incentive": "0",
                "dividends": "0",
                "validator_trust": "0.8",
                "consensus": "0.8",
                "total_alpha_stake": "1200",
                "stake": "1200",
                "axon": {"ip": "127.0.0.1", "port": 8091},
            },
            {
                "uid": 75,
                "hotkey": validator_b.hotkey.ss58_address,
                "active": True,
                "validator_permit": True,
                "updated_blocks": 3,
                "rank": 0.8,
                "emission": "1",
                "incentive": "0",
                "dividends": "0",
                "validator_trust": "0.7",
                "consensus": "0.7",
                "total_alpha_stake": "1100",
                "stake": "1100",
                "axon": {"ip": "127.0.0.1", "port": 8092},
            },
            {
                "uid": 101,
                "hotkey": miner_a.ss58_address,
                "active": True,
                "validator_permit": False,
                "updated_blocks": 4,
                "rank": 0.6,
                "emission": "12.5",
                "incentive": "0.6",
                "dividends": "0",
                "validator_trust": "0",
                "consensus": "0.5",
                "total_alpha_stake": "500",
                "stake": "500",
                "axon": {"ip": "127.0.0.1", "port": 9091},
            },
            {
                "uid": 102,
                "hotkey": miner_b.ss58_address,
                "active": True,
                "validator_permit": False,
                "updated_blocks": 5,
                "rank": 0.2,
                "emission": "5",
                "incentive": "0.2",
                "dividends": "0",
                "validator_trust": "0",
                "consensus": "0.2",
                "total_alpha_stake": "200",
                "stake": "200",
                "axon": {"ip": "127.0.0.1", "port": 9092},
            },
        ],
    }

    results = {}
    for name, wallet, payload in [
        ("previous_epoch_validator_a", validator_a, prev_payload_v1),
        ("previous_epoch_validator_b", validator_b, prev_payload_v2),
        ("current_epoch_validator_a", validator_a, current_payload_v1),
        ("current_epoch_validator_b", validator_b, current_payload_v2),
    ]:
        ok, message = _post_signed(report_url, wallet, payload)
        results[name] = {"ok": ok, "message": message}
        if not ok:
            raise RuntimeError(f"Failed {name}: {message}")

    ok, message = _post_signed(network_snapshot_url, validator_a, network_snapshot)
    results["network_snapshot"] = {"ok": ok, "message": message}
    if not ok:
        raise RuntimeError(f"Failed network snapshot post: {message}")

    miner_runtime = Miner.__new__(Miner)
    miner_runtime.model_manifest = dict(manifest_a)
    synapse = DetectionSynapse(chunks=[batch.get("hands") or [] for batch in batches])
    synapse = asyncio.run(Miner.forward(miner_runtime, synapse))

    hand_ids = sorted(
        {
            str(hand_id)
            for ref in active_chunk.get("batch_refs", [])
            if isinstance(ref, dict)
            for hand_id in ref.get("hand_ids", [])
            if str(hand_id).strip()
        }
    )
    mark_evaluated_result = _http_json(
        urljoin(BACKEND_BASE_URL, "/internal/eval/mark-evaluated"),
        method="POST",
        headers={"x-eval-secret": EVAL_SECRET},
        payload={
            "hand_ids": hand_ids,
            "chunkId": active_chunk["chunkId"],
            "validatorId": "e2e-local",
        },
    )

    current_response = _http_json(urljoin(BACKEND_BASE_URL, "/api/v1/competition/current"))
    leaderboard_response = _http_json(urljoin(BACKEND_BASE_URL, "/api/v1/competition/leaderboard"))
    weights_response = _http_json(
        urljoin(BACKEND_BASE_URL, "/internal/competition/current/weights"),
        headers={"x-eval-secret": EVAL_SECRET},
    )

    summary = {
        "reports_posted": results,
        "current_epoch": current_epoch["epochId"],
        "previous_epoch": previous_epoch["epochId"],
        "active_chunk_id": active_chunk["chunkId"],
        "miner_roundtrip": {
            "returned_scores": len(synapse.risk_scores or []),
            "returned_predictions": len(synapse.predictions or []),
            "returned_manifest_model": (synapse.model_manifest or {}).get("model_name"),
        },
        "mark_evaluated_result": mark_evaluated_result.get("data"),
        "leaderboard_rows": leaderboard_response["data"]["rows"][:5],
        "latest_settled_winner": current_response["data"].get("latestSettledWinner"),
        "settlement_weights": weights_response["data"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
