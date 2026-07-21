"""Typed session lease models kept separate from HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _find_forbidden(value: Any, path: str) -> list[str]:
    forbidden = {"is_bot", "is_human", "ground_truth", "label", "bot_family"}
    if isinstance(value, dict):
        leaked: list[str] = []
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in forbidden:
                leaked.append(child_path)
            leaked.extend(_find_forbidden(child, child_path))
        return leaked
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _find_forbidden(child, f"{path}[{index}]")
        ]
    return []


@dataclass(frozen=True)
class LeasedSession:
    payload: dict[str, Any]
    is_bot: bool


@dataclass(frozen=True)
class SessionLease:
    lease_id: str
    window_id: str
    dataset_hash: str
    expires_at: str
    sessions: list[LeasedSession]
    completed_at: str | None = None

    @classmethod
    def from_payload(cls, value: Any) -> "SessionLease":
        if not isinstance(value, dict):
            raise ValueError("Session lease response must be an object")
        sessions_raw = value.get("sessions")
        if not isinstance(sessions_raw, list) or not sessions_raw:
            raise ValueError("Session lease contains no sessions")
        sessions: list[LeasedSession] = []
        seen_session_ids: set[str] = set()
        for index, item in enumerate(sessions_raw):
            if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                raise ValueError(f"sessions[{index}] has an invalid payload")
            if not isinstance(item.get("is_bot"), bool):
                raise ValueError(f"sessions[{index}] has no boolean ground truth")
            miner_payload = dict(item["payload"])
            leaked = _find_forbidden(miner_payload, f"sessions[{index}].payload")
            if leaked:
                raise ValueError(
                    f"sessions[{index}].payload leaks labels: {sorted(leaked)}"
                )
            session_id = str(miner_payload.get("session_id") or "").strip()
            if not session_id or session_id in seen_session_ids:
                raise ValueError(
                    f"sessions[{index}] has a missing or duplicate session_id"
                )
            seen_session_ids.add(session_id)
            sessions.append(LeasedSession(payload=miner_payload, is_bot=item["is_bot"]))
        lease_id = str(value.get("lease_id") or "").strip()
        window_id = str(value.get("window_id") or "").strip()
        if not lease_id or not window_id:
            raise ValueError("Session lease requires lease_id and window_id")
        if any(
            str(session.payload.get("window_id") or "") != window_id
            for session in sessions
        ):
            raise ValueError("Session payload window_id does not match its lease")
        dataset_hash = str(value.get("dataset_hash") or "").strip()
        if not dataset_hash:
            raise ValueError("Session lease requires a dataset_hash")
        return cls(
            lease_id=lease_id,
            window_id=window_id,
            dataset_hash=dataset_hash,
            expires_at=str(value.get("expires_at") or ""),
            sessions=sessions,
            completed_at=(
                str(value["completed_at"]) if value.get("completed_at") else None
            ),
        )


@dataclass
class ValidationRound:
    lease: SessionLease
    round_id: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if not self.round_id:
            self.round_id = self.lease.window_id

    @property
    def labels(self) -> list[int]:
        return [1 if session.is_bot else 0 for session in self.lease.sessions]

    @property
    def miner_sessions(self) -> list[dict[str, Any]]:
        return [session.payload for session in self.lease.sessions]
