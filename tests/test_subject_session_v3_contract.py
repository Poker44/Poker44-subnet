from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(
        (ROOT / "contracts" / "subject-session.v3.schema.json").read_text()
    )


def subject_session_v3() -> dict:
    return json.loads((ROOT / "examples" / "subject-session.v3.json").read_text())


def test_strategic_example_matches_v3_contract(schema):
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(subject_session_v3(), schema)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("telemetry", {"events": []}),
        ("is_bot", True),
        ("tournament_id", "private"),
        ("decision_time_ms", 1200),
        ("cards", ["As", "Kh"]),
        ("stack", 10000),
    ],
)
def test_v3_contract_rejects_non_strategic_and_private_fields(schema, key, value):
    session = copy.deepcopy(subject_session_v3())
    session[key] = value

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(session, schema)
