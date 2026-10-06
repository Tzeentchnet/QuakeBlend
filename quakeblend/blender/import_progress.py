"""Bounded Blender progress reporting for synchronous imports."""

from __future__ import annotations

from typing import Protocol


class ProgressWindowManager(Protocol):
    def progress_begin(self, minimum: int, maximum: int) -> None: ...

    def progress_update(self, value: int) -> None: ...

    def progress_end(self) -> None: ...


class ImportProgress:
    """Report monotonic progress without flooding Blender's event queue."""

    minimum = 0
    maximum = 1000

    def __init__(
        self,
        window_manager: ProgressWindowManager,
        *,
        min_update_delta: int = 10,
    ) -> None:
        if min_update_delta < 1:
            raise ValueError("min_update_delta must be at least 1")
        self._window_manager = window_manager
        self._min_update_delta = min_update_delta
        self._last_value = self.minimum
        self._active = False
        self._entered = False

    def __enter__(self) -> "ImportProgress":
        if self._entered:
            raise RuntimeError("import progress contexts cannot be reused")
        self._entered = True
        self._window_manager.progress_begin(self.minimum, self.maximum)
        self._active = True
        return self

    def __exit__(self, _exc_type, exc, _traceback) -> bool:
        cleanup_error: Exception | None = None
        if exc is None:
            try:
                self.phase(self.maximum)
            except Exception as error:
                cleanup_error = error

        try:
            self._window_manager.progress_end()
        except Exception as error:
            if cleanup_error is None:
                cleanup_error = error
            else:
                cleanup_error.add_note(f"progress_end also failed: {error!r}")
        finally:
            self._active = False

        if exc is not None:
            if cleanup_error is not None:
                exc.add_note(f"progress cleanup failed: {cleanup_error!r}")
            return False
        if cleanup_error is not None:
            raise cleanup_error
        return False

    def phase(self, value: int) -> None:
        """Force a phase boundary while preserving monotonic bounds."""
        self._emit(value, force=True)

    def update(
        self,
        completed: int,
        total: int,
        *,
        start: int,
        end: int,
    ) -> None:
        """Map a completed-item count onto one bounded progress phase."""
        if start > end:
            raise ValueError("progress phase start must not exceed its end")
        bounded_start = min(max(start, self.minimum), self.maximum)
        bounded_end = min(max(end, self.minimum), self.maximum)
        if total <= 0:
            ratio = 1.0
        else:
            ratio = min(max(completed, 0), total) / total
        value = round(bounded_start + (bounded_end - bounded_start) * ratio)
        self._emit(value, force=False)

    def _emit(self, value: int, *, force: bool) -> None:
        if not self._active:
            raise RuntimeError("import progress is not active")
        bounded = min(max(value, self.minimum), self.maximum)
        bounded = max(bounded, self._last_value)
        if bounded == self._last_value:
            return
        if (
            not force
            and bounded != self.maximum
            and bounded - self._last_value < self._min_update_delta
        ):
            return
        self._window_manager.progress_update(bounded)
        self._last_value = bounded
