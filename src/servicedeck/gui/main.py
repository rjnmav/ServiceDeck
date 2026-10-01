"""Entrypoint for launching the ServiceDeck PySide6 desktop GUI client."""

import argparse
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import servicedeck.gui.resources.resources_rc  # noqa: F401
from servicedeck.api_client import ServiceDeckClient
from servicedeck.gui.views.main_window import MainWindow


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the GUI client."""
    parser = argparse.ArgumentParser(
        prog="servicedeck-gui",
        description="ServiceDeck 2.0 — PySide6 Desktop GUI Client",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=os.getenv("SERVICEDECK_BACKEND_URL", "http://127.0.0.1:8000"),
        help="ServiceDeck backend REST API URL (default: http://127.0.0.1:8000)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the ServiceDeck PySide6 desktop application."""
    args = parse_args(argv)

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setApplicationName("ServiceDeck")
    app.setApplicationDisplayName("ServiceDeck — Systemd Service Manager")
    app.setApplicationVersion("2.0.0")
    app.setWindowIcon(QIcon(":/assets/servicedeck.svg"))

    client = ServiceDeckClient(base_url=args.url)
    window = MainWindow(client=client)
    window.showMaximized()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
