"""
Application logging configuration.
"""

import logging
import sys

from app.core.config import settings


def configure_logging() -> None:
    """Configure application-wide logging."""

    level = logging.DEBUG if settings.debug else logging.INFO

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for a module."""
    return logging.getLogger(name)