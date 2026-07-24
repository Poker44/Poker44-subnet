from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]


def subject_session_v2() -> dict:
    return json.loads((ROOT / "examples" / "subject-session.v2.json").read_text())


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(
        (ROOT / "contracts" / "subject-session.v2.schema.json").read_text()
    )


def test_tournament_session_example_matches_v2_contract(schema):
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(subject_session_v2(), schema)


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        (("hands", 0, "actions", 0), "occurred_at", "2026-07-25T15:00:00Z"),
        (("telemetry", "events", 0), "source", "client"),
        (("telemetry", "events", 0), "target", "action-raise"),
        ((), "is_bot", True),
        ((), "tournament_id", "private-tournament-id"),
    ],
)
def test_v2_contract_rejects_removed_or_ground_truth_fields(schema, path, key, value):
    session = subject_session_v2()
    target = session
    for part in path:
        target = target[part]
    target[key] = value

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(session, schema)


def test_v2_contract_rejects_raw_coordinates(schema):
    session = copy.deepcopy(subject_session_v2())
    session["telemetry"]["events"][0]["value"]["x"] = 314

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(session, schema)
