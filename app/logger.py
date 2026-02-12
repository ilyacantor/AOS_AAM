"""
AAM Structured Logging.

Provides a configured logger factory. All modules should use:
    from .logger import get_logger
    logger = get_logger(__name__)
"""
import logging
import sys

from .config import settings

_configured = False


def _configure_logging():
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    )

    root = logging.getLogger("aam")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'aam' namespace."""
    _configure_logging()
    return logging.getLogger(f"aam.{name}")
