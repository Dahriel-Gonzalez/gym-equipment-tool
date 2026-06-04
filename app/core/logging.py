"""Structured logging via structlog.

JSON lines in production (machine-parseable for log aggregators); pretty,
coloured console output in DEBUG. The request-ID middleware binds `request_id`
(and method/path) into structlog's contextvars, so EVERY log line emitted while
handling a request automatically carries them — no need to thread the id through
function calls.
"""
from __future__ import annotations

import logging

import structlog


def configure_logging(*, debug: bool = False) -> None:
    """Configure structlog once, at application startup."""
    shared = [
        # Pull contextvars (request_id, method, path) into every event.
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if debug:
        processors = [*shared, structlog.dev.ConsoleRenderer()]
    else:
        processors = [
            *shared,
            structlog.processors.format_exc_info,  # render exceptions into the JSON
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        # INFO and above; everything below is dropped cheaply.
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),  # writes to stdout
        cache_logger_on_first_use=True,
    )


# Module-level logger for the app to import and use.
logger = structlog.get_logger("gym_api")
