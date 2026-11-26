"""Structured logging with ContextVar-based call_id correlation."""

from __future__ import annotations

import contextvars
import logging
import sys

call_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("call_id", default="-")


class CallContextFilter(logging.Filter):
    """Injects the active call_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.call_id = call_id_ctx.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CallContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | call=%(call_id)s | %(name)s | %(message)s"
        )
    )

    root.handlers.clear()
    root.addHandler(handler)
