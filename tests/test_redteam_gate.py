from poker44.validator.evaluation.redteam_gate import audit_redteam_leakage


def session(pointer_moves: int, *, padding: str = "") -> dict[str, object]:
    return {
        "schema_version": "2",
        "session_id": "session_example",
        "window_id": "window_example",
        "hands": [{"hand_number": index + 1, "actions": []} for index in range(3)],
        "telemetry": {
            "events": [
                {
                    "sequence": index,
                    "offset_ms": index * 100,
                    "event_type": "pointer_move",
                    "target_category": "other",
                    "value": {"pointer": "mouse", "x_bucket": 1, "y_bucket": 1},
                }
                for index in range(pointer_moves)
            ],
            "summary": {"padding": padding},
        },
    }


def test_gate_rejects_current_pointer_volume_shortcut() -> None:
    sessions = [session(380), session(520), session(6), session(12)]
    result = audit_redteam_leakage(sessions, [0, 0, 1, 1], threshold=0.15)

    assert result.passed is False
    assert result.skipped is False
    assert result.reward > result.threshold
    assert result.feature in {"payload_bytes", "telemetry_events", "pointer_moves"}
    assert result.balanced_accuracy == 1.0


def test_gate_accepts_shape_matched_sessions() -> None:
    sessions = [session(30), session(40), session(30), session(40)]
    result = audit_redteam_leakage(sessions, [0, 0, 1, 1], threshold=0.15)

    assert result.passed is True
    assert result.reward == 0.0


def test_gate_checks_serialized_size_even_when_event_counts_match() -> None:
    sessions = [
        session(20, padding="human-a" * 300),
        session(20, padding="human-b" * 300),
        session(20),
        session(20),
    ]
    result = audit_redteam_leakage(sessions, [0, 0, 1, 1], threshold=0.15)

    assert result.passed is False
    assert result.feature == "payload_bytes"


def test_gate_skips_single_class_operational_windows() -> None:
    result = audit_redteam_leakage([session(20), session(20)], [1, 1])

    assert result.skipped is True
    assert result.passed is False


def strategic_session(action: str, *, context_shift: bool = False) -> dict[str, object]:
    return {
        "schema_version": "3",
        "session_id": f"session_{action}_{context_shift}",
        "window_id": "window_example",
        "decisions": [
            {
                "decision_number": index + 1,
                "phase": "turn" if context_shift and index == 0 else (
                    "preflop" if index < 9 else "flop"
                ),
                "position_group": ("early", "late", "blinds")[index % 3],
                "pressure": "facing_bet" if index % 2 else "no_call",
                "action_type": action,
                "size_bucket": (
                    "half_pot" if action in {"bet", "raise"} else "not_applicable"
                ),
                "is_all_in": False,
            }
            for index in range(12)
        ],
    }


def test_gate_accepts_matched_contexts_when_only_strategy_differs() -> None:
    sessions = [
        strategic_session("check"),
        strategic_session("call"),
        strategic_session("raise"),
        strategic_session("fold"),
    ]
    result = audit_redteam_leakage(sessions, [0, 0, 1, 1], threshold=0.15)

    assert result.passed is True
    assert result.reward == 0.0


def test_gate_rejects_v3_context_distribution_shortcuts() -> None:
    sessions = [
        strategic_session("check"),
        strategic_session("call"),
        strategic_session("raise", context_shift=True),
        strategic_session("fold", context_shift=True),
    ]
    result = audit_redteam_leakage(sessions, [0, 0, 1, 1], threshold=0.15)

    assert result.passed is False
    assert result.feature == "strategic_context_signature"
