"""
Logging configuration for NJ Affordable Housing Tracker.

Configures structlog for console output. Import and call configure_logging()
from script entry points (e.g., main()) to enable visible logging.
"""

import logging
import os

import structlog


def configure_logging(level: str = None) -> None:
    """
    Configure structlog for console output.
    Skips configuration if STRUCTLOG_DISABLE=1 (e.g., during tests).
    """
    if os.environ.get("STRUCTLOG_DISABLE") == "1":
        return

    log_level = level or os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
