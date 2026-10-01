"""Structured logging configuration for ServiceDeck backend."""

import logging
import sys


def setup_logging(log_level: str = "INFO", debug: bool = False) -> None:
    """Configure structured logging for the backend application."""
    level = logging.DEBUG if debug else getattr(logging, log_level.upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    # Root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for existing_handler in list(root_logger.handlers):
        root_logger.removeHandler(existing_handler)

    root_logger.addHandler(handler)

    # Adjust third-party loggers if needed
    logging.getLogger("uvicorn.access").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("dbus_fast").setLevel(logging.WARNING if not debug else logging.DEBUG)


def get_logger(name: str) -> logging.Logger:
    """Convenience function to get a logger with a hierarchical name."""
    return logging.getLogger(name)
