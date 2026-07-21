"""Convert non-negative validator-local scores into a weight preview."""

from __future__ import annotations

import numpy as np


def retain_top_scores(scores: np.ndarray, max_winners: int = 10) -> np.ndarray:
    """Keep at most the strongest positive scores with deterministic UID ties."""
    if max_winners <= 0:
        raise ValueError("max_winners must be positive")
    clean = np.clip(
        np.nan_to_num(np.asarray(scores, dtype=float), nan=0.0, posinf=0.0, neginf=0.0),
        0.0,
        None,
    )
    positive = np.flatnonzero(clean > 0.0)
    ranked = sorted(positive.tolist(), key=lambda uid: (-clean[uid], uid))
    retained = np.zeros_like(clean)
    winners = ranked[:max_winners]
    retained[winners] = clean[winners]
    return retained


def normalized_weight_rows(
    scores: np.ndarray, max_winners: int = 10
) -> list[dict[str, float | int]]:
    clean = retain_top_scores(scores, max_winners=max_winners)
    total = float(clean.sum())
    if total <= 0.0:
        return []
    return [
        {"uid": int(uid), "weight": float(value / total)}
        for uid, value in enumerate(clean)
        if value > 0.0
    ]


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
