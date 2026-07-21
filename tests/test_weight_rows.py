import numpy as np

from poker44.validator.settlement.weights import (
    normalized_weight_rows,
    retain_top_scores,
    weight_rows,
)


def test_zero_scores_produce_no_fake_uid_zero_weight():
    assert normalized_weight_rows(np.zeros(4)) == []


def test_weight_rows_serialize_the_processed_sdk_vector():
    prepared = (
        np.asarray([2, 7]),
        np.asarray([0.25, 0.75]),
        np.asarray([2, 7]),
        np.asarray([16384, 49151]),
    )
    assert weight_rows(prepared) == [
        {"uid": 2, "weight": 0.25},
        {"uid": 7, "weight": 0.75},
    ]


def test_only_ten_strongest_miners_receive_progressive_weights():
    scores = np.asarray([float(value) for value in range(1, 13)])
    retained = retain_top_scores(scores)
    rows = normalized_weight_rows(scores)

    assert np.flatnonzero(retained).tolist() == list(range(2, 12))
    assert len(rows) == 10
    assert rows[-1]["weight"] > rows[0]["weight"]
