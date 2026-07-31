"""Strict miner-visible data contracts.

Ground truth and provenance deliberately live outside these objects. Keeping
v4/v4.1 validation in one module prevents protocol, axon and model code from
growing independent (and eventually inconsistent) allowlists.
"""

from __future__ import annotations

from typing import Any

V4_SESSION_KEYS = {"schema_version", "item_id", "window_id", "decisions"}
STRATEGIC_DECISION_KEYS = {
    "decision_number",
    "phase",
    "position_group",
    "pressure",
    "action_type",
    "size_bucket",
    "is_all_in",
}
FORBIDDEN_KEYS = {
    "actor_group",
    "bot_family",
    "ground_truth",
    "is_bot",
    "is_human",
    "label",
}


def find_forbidden(value: Any, path: str = "session") -> list[str]:
    leaked: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_KEYS:
                leaked.append(child_path)
            leaked.extend(find_forbidden(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaked.extend(find_forbidden(child, f"{path}[{index}]"))
    return leaked


def validate_v4_micro_session(session: dict[str, Any], index: int) -> None:
    prefix = f"sessions[{index}]"
    if set(session) != V4_SESSION_KEYS:
        raise ValueError(f"{prefix} does not match the micro-session contract")
    schema_version = str(session.get("schema_version") or "")
    if schema_version != "4.1":
        raise ValueError(f"{prefix} has an unsupported micro-session schema")
    if not str(session.get("item_id") or "").strip():
        raise ValueError(f"{prefix} has no item_id")
    if not str(session.get("window_id") or "").strip():
        raise ValueError(f"{prefix} has no window_id")
    decisions = session.get("decisions")
    required_decisions = 4
    required_postflop = 1
    if not isinstance(decisions, list) or len(decisions) != required_decisions:
        raise ValueError(
            f"{prefix} must contain exactly {required_decisions} strategic decisions"
        )
    postflop = 0
    for decision_index, decision in enumerate(decisions):
        decision_path = f"{prefix}.decisions[{decision_index}]"
        if not isinstance(decision, dict) or set(decision) != STRATEGIC_DECISION_KEYS:
            raise ValueError(f"{decision_path} does not match the strategic contract")
        if not isinstance(decision["decision_number"], int):
            raise ValueError(f"{decision_path}.decision_number must be an integer")
        if not isinstance(decision["is_all_in"], bool):
            raise ValueError(f"{decision_path}.is_all_in must be boolean")
        for key in (
            "phase",
            "position_group",
            "pressure",
            "action_type",
            "size_bucket",
        ):
            if not isinstance(decision[key], str) or not decision[key].strip():
                raise ValueError(f"{decision_path}.{key} must be a non-empty string")
        if decision["phase"].lower() in {"flop", "turn", "river"}:
            postflop += 1
    if postflop < required_postflop:
        raise ValueError(
            f"{prefix} must contain at least {required_postflop} postflop decision"
        )
