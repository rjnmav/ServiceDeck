"""Unified command-line interface for ServiceDeck 2.0."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """ServiceDeck CLI dispatcher."""
    parser = argparse.ArgumentParser(
        prog="servicedeck",
        description="ServiceDeck 2.0 — Linux system service management and monitoring platform",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Backend subcommand
    backend_parser = subparsers.add_parser(
        "backend",
        help="Start the ServiceDeck REST API backend server",
    )
    backend_parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host to bind to (default: 127.0.0.1)",
    )
    backend_parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    backend_parser.add_argument(
        "--log-level",
        type=str,
        choices=["debug", "info", "warning", "error"],
        default=None,
        help="Logging level",
    )
    backend_parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug mode",
    )

    # GUI subcommand
    gui_parser = subparsers.add_parser(
        "gui",
        help="Start the ServiceDeck PySide6 desktop GUI client",
    )
    gui_parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="ServiceDeck backend URL (default: http://127.0.0.1:8000)",
    )

    # Remote subcommand (Phase 2)
    remote_parser = subparsers.add_parser(
        "remote",
        help="Manage remote ServiceDeck instances over SSH (Phase 2)",
    )
    remote_subparsers = remote_parser.add_subparsers(dest="remote_subcommand")
    remote_subparsers.add_parser("add", help="Pair and add a remote Linux machine")
    remote_subparsers.add_parser("list", help="List configured remote machines")
    remote_subparsers.add_parser("remove", help="Remove or unpair a remote machine")
    remote_subparsers.add_parser("status", help="Check status of a remote machine")

    args, unknown = parser.parse_known_args(argv)

    if args.subcommand == "remote":
        print(
            "ServiceDeck 2.0 remote trusted management is part of Phase 2 (SSH tunnels and persistent authorization).",
            file=sys.stderr,
        )
        print("Run 'servicedeck remote --help' for upcoming commands.", file=sys.stderr)
        return 0

    if args.subcommand == "gui":
        from servicedeck.gui.main import main as gui_main

        gui_args: list[str] = []
        if args.url:
            gui_args.extend(["--url", args.url])
        gui_args.extend(unknown)
        return gui_main(gui_args)

    if args.subcommand == "backend" or args.subcommand is None:
        # Default to running the backend if no subcommand is given
        from servicedeck.backend.main import main as backend_main

        # Pass remaining arguments to backend
        backend_args: list[str] = []
        if args.host:
            backend_args.extend(["--host", args.host])
        if args.port:
            backend_args.extend(["--port", str(args.port)])
        if args.log_level:
            backend_args.extend(["--log-level", args.log_level])
        if args.debug:
            backend_args.append("--debug")
        backend_args.extend(unknown)

        return backend_main(backend_args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
