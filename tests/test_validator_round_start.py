from types import MethodType, SimpleNamespace

import pytest

from poker44.validator.round_start.mixin import ValidatorRoundStartMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("launch_status", ["DRAFT", ""])
async def test_unlaunched_lease_is_rejected_before_miners_are_queried(launch_status):
    lease = SimpleNamespace(
        window_id="window-1",
        launch_status=launch_status,
    )
    harness = SimpleNamespace(
        subnet_data=SimpleNamespace(
            current_window=lambda: {"window_id": "window-1", "status": "AVAILABLE"},
            acquire_lease=lambda _window_id: lease,
        ),
        round_manager=SimpleNamespace(retry_delay=lambda _window_id: 0),
    )
    harness._start_validation_round = MethodType(
        ValidatorRoundStartMixin._start_validation_round, harness
    )

    with pytest.raises(RuntimeError, match="unlaunched"):
        await harness._start_validation_round()
