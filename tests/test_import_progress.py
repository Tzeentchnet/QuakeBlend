"""Tests for synchronous Blender import progress reporting."""

from __future__ import annotations

import pytest

from quakeblend.blender.import_progress import ImportProgress


class _FakeWindowManager:
    def __init__(
        self,
        *,
        fail_update_at: int | None = None,
        fail_end: bool = False,
    ) -> None:
        self.events: list[tuple] = []
        self.fail_update_at = fail_update_at
        self.fail_end = fail_end

    def progress_begin(self, minimum: int, maximum: int) -> None:
        self.events.append(("begin", minimum, maximum))

    def progress_update(self, value: int) -> None:
        self.events.append(("update", value))
        if value == self.fail_update_at:
            raise RuntimeError("progress update failed")

    def progress_end(self) -> None:
        self.events.append(("end",))
        if self.fail_end:
            raise RuntimeError("progress end failed")


def test_progress_is_bounded_monotonic_and_throttled() -> None:
    window_manager = _FakeWindowManager()

    with ImportProgress(window_manager) as progress:
        for completed in range(10_001):
            progress.update(completed, 10_000, start=-100, end=1100)

    updates = [event[1] for event in window_manager.events if event[0] == "update"]
    assert window_manager.events[0] == ("begin", 0, 1000)
    assert window_manager.events[-1] == ("end",)
    assert updates[-1] == 1000
    assert updates == sorted(updates)
    assert all(0 <= value <= 1000 for value in updates)
    assert len(updates) <= 100


def test_progress_end_failure_does_not_mask_import_failure() -> None:
    window_manager = _FakeWindowManager(fail_end=True)
    original = ValueError("import failed")

    with pytest.raises(ValueError) as caught:
        with ImportProgress(window_manager):
            raise original

    assert caught.value is original
    assert window_manager.events[-1] == ("end",)
    assert any("progress cleanup failed" in note for note in original.__notes__)


def test_progress_end_runs_when_success_completion_update_fails() -> None:
    window_manager = _FakeWindowManager(fail_update_at=1000)

    with pytest.raises(RuntimeError, match="progress update failed"):
        with ImportProgress(window_manager):
            pass

    assert window_manager.events[-1] == ("end",)
