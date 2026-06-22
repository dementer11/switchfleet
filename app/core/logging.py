from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.services.report_sanitizer import sanitize_report_metadata
from app.utils.masking import mask_secrets


def redact_log_event(_logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    """Structlog processor that defensively masks secret-like log fields."""
    sanitized = sanitize_report_metadata(event_dict)
    event = sanitized.get("event")
    if isinstance(event, str):
        sanitized["event"] = mask_secrets(event)
    return sanitized


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            redact_log_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
