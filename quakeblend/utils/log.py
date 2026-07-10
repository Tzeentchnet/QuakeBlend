"""Tiny logging helper that routes to both stdout and Blender's report system.

The formats layer uses :func:`get_logger` (stdout only). The blender layer uses
:func:`report` to additionally surface messages in the Blender info bar.
"""

from __future__ import annotations

import logging
from typing import Iterable, Protocol


class ReportOperator(Protocol):
    def report(self, level: set[str], message: str) -> None: ...

_LOGGER_NAME = "quakeblend"


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)


def configure_default(level: int = logging.INFO) -> None:
    logger = get_logger()
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[QuakeBlend %(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)


def report(operator: ReportOperator, level: Iterable[str], message: str) -> None:
    """Forward a message to a Blender operator's report channel and the logger."""
    operator.report(set(level), message)
    log_level = logging.WARNING if "WARNING" in level else (
        logging.ERROR if "ERROR" in level else logging.INFO
    )
    get_logger().log(log_level, message)
