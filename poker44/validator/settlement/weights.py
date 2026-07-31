"""Deterministic winner-takes-all weight construction."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


def winner_uid(evaluations: Sequence[Any]) -> int | None:
    """Return the highest positive finite score, breaking exact ties by UID."""

    candidates = [
        (float(item.quality_score), int(item.uid))
        for item in evaluations
        if np.isfinite(float(item.quality_score)) and float(item.quality_score) > 0.0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: (-row[0], row[1]))[1]


def ranked_score_rows(evaluations: Sequence[Any]) -> list[dict[str, Any]]:
    """Serialize every miner score and its binary round reward."""

    clean = sorted(
        evaluations,
        key=lambda item: (
            -float(item.quality_score)
            if np.isfinite(float(item.quality_score))
            else 0.0,
            int(item.uid),
        ),
    )
    winner = winner_uid(evaluations)
    return [
        {
            "uid": int(item.uid),
            "hotkey": str(item.hotkey),
            "quality_score": (
                float(item.quality_score)
                if np.isfinite(float(item.quality_score))
                else 0.0
            ),
            "rank": index + 1,
            "round_reward": 1.0 if int(item.uid) == winner else 0.0,
            "is_winner": int(item.uid) == winner,
            "metrics": dict(item.metrics),
            "model_version": item.model_version,
            "error": item.error,
        }
        for index, item in enumerate(clean)
    ]


def one_hot_scores(size: int, uid: int | None) -> np.ndarray:
    scores = np.zeros(size, dtype=np.float32)
    if uid is not None:
        if uid < 0 or uid >= size:
            raise ValueError("winner UID is outside the metagraph")
        scores[uid] = 1.0
    return scores


def weight_rows(prepared_weights) -> list[dict[str, float | int]]:
    """Serialize the exact SDK-processed vector used for chain submission."""

    if prepared_weights is None:
        return []
    uids, weights, _uint_uids, _uint_weights = prepared_weights
    return [
        {"uid": int(uid), "weight": float(weight)}
        for uid, weight in zip(uids, weights)
        if float(weight) > 0.0
    ]
