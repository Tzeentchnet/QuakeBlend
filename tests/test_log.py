"""Tests for ``quakeblend.utils.log``."""

from __future__ import annotations

import io
import logging

import pytest

from quakeblend.utils import log as qb_log


@pytest.fixture(autouse=True)
def _reset_quakeblend_logger() -> None:
    logger = qb_log.get_logger()
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate

    for handler in original_handlers:
        logger.removeHandler(handler)

    logger.setLevel(logging.NOTSET)
    logger.propagate = True

    yield

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    for handler in original_handlers:
        logger.addHandler(handler)

    logger.setLevel(original_level)
    logger.propagate = original_propagate


def test_configure_default_filters_and_formats_messages() -> None:
    logger = qb_log.get_logger()

    qb_log.configure_default(logging.WARNING)
    assert len(logger.handlers) == 1

    stream = io.StringIO()
    logger.handlers[0].setStream(stream)

    logger.info("hidden")
    logger.error("visible")

    assert logger.level == logging.WARNING
    assert stream.getvalue() == "[QuakeBlend ERROR] visible\n"


def test_report_forwards_message_to_operator_and_logger(caplog: pytest.LogCaptureFixture) -> None:
    class FakeOperator:
        def __init__(self) -> None:
            self.calls: list[tuple[set[str], str]] = []

        def report(self, level: set[str], message: str) -> None:
            self.calls.append((level, message))

    operator = FakeOperator()

    with caplog.at_level(logging.INFO, logger="quakeblend"):
        qb_log.report(operator, ["WARNING"], "careful")

    assert operator.calls == [({"WARNING"}, "careful")]
    assert caplog.records[-1].levelno == logging.WARNING
    assert caplog.records[-1].message == "careful"


def test_report_handles_empty_messages_and_unusual_levels(caplog: pytest.LogCaptureFixture) -> None:
    class FakeOperator:
        def __init__(self) -> None:
            self.calls: list[tuple[set[str], str]] = []

        def report(self, level: set[str], message: str) -> None:
            self.calls.append((level, message))

    operator = FakeOperator()

    with caplog.at_level(logging.INFO, logger="quakeblend"):
        qb_log.report(operator, [], "")
        qb_log.report(operator, ["warning", "ODD"], "strange")

    assert operator.calls == [(set(), ""), ({"warning", "ODD"}, "strange")]
    assert [record.levelno for record in caplog.records] == [logging.INFO, logging.INFO]
    assert [record.message for record in caplog.records] == ["", "strange"]


def test_report_exception_forwards_ui_message_and_active_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeOperator:
        def __init__(self) -> None:
            self.calls: list[tuple[set[str], str]] = []

        def report(self, level: set[str], message: str) -> None:
            self.calls.append((level, message))

    operator = FakeOperator()

    with caplog.at_level(logging.ERROR, logger="quakeblend"):
        try:
            raise RuntimeError("broken brush")
        except RuntimeError as exc:
            qb_log.report_exception(operator, f"MAP import failed: {exc}")

    assert operator.calls == [({"ERROR"}, "MAP import failed: broken brush")]
    assert caplog.records[-1].name == "quakeblend"
    assert caplog.records[-1].levelno == logging.ERROR
    assert caplog.records[-1].message == "MAP import failed: broken brush"
    assert "Traceback (most recent call last):" in caplog.text
    assert 'raise RuntimeError("broken brush")' in caplog.text
    assert "RuntimeError: broken brush" in caplog.text
