from types import SimpleNamespace

import numpy as np

from poker44.validator.settlement.weights import (
    one_hot_scores,
    ranked_score_rows,
    weight_rows,
    winner_uid,
)


def evaluation(uid, score):
    return SimpleNamespace(uid=uid, hotkey=f"hotkey-{uid}", quality_score=score,
                           metrics={}, model_version="test", error=None)


def test_winner_is_highest_positive_score_with_uid_tie_break():
    rows = [evaluation(8, 0.8), evaluation(2, 0.8), evaluation(1, 0.0)]
    assert winner_uid(rows) == 2
    assert one_hot_scores(10, 2).tolist() == [0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
    ranked = ranked_score_rows(rows)
    assert [row["uid"] for row in ranked] == [2, 8, 1]
    assert [row["round_reward"] for row in ranked] == [1.0, 0.0, 0.0]


def test_no_positive_finite_score_has_no_winner():
    assert winner_uid([evaluation(1, 0.0), evaluation(2, float("nan"))]) is None


def test_weight_rows_serialize_the_processed_sdk_vector():
    prepared = (np.asarray([2]), np.asarray([1.0]), np.asarray([2]), np.asarray([65535]))
    assert weight_rows(prepared) == [{"uid": 2, "weight": 1.0}]
