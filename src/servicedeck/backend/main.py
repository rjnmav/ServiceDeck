"""Executable entrypoint for the ServiceDeck backend server."""

import argparse
import sys

import uvicorn

from servicedeck.backend.app.application import create_app
from servicedeck.backend.config.settings import Settings
from servicedeck.backend.logging import get_logger, setup_logging

logger = get_logger(__name__)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for backend service."""
    parser = argparse.ArgumentParser(
        prog="servicedeck-backend",
        description="ServiceDeck 2.0 systemd service management backend",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["debug", "info", "warning", "error"],
        default=None,
        help="Logging level (default: info)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug mode and reload",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Start the ServiceDeck backend server."""
    args = parse_args(argv)

    # Base settings from environment
    settings = Settings()

    # Override with CLI args if specified
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.log_level:
        settings.log_level = args.log_level.upper()
    if args.debug:
        settings.debug = True

    setup_logging(log_level=settings.log_level, debug=settings.debug)

    logger.info(
        "Starting %s on http://%s:%d (debug=%s)",
        settings.app_name,
        settings.host,
        settings.port,
        settings.debug,
    )

    app = create_app(settings=settings)

    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
        )
        return 0
    except KeyboardInterrupt:
        logger.info("ServiceDeck backend stopped by user.")
        return 0
    except Exception as exc:
        logger.critical("Fatal error running ServiceDeck backend: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
