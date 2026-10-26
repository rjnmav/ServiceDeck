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

    # Remote subcommand
    remote_parser = subparsers.add_parser(
        "remote",
        help="Manage remote ServiceDeck instances over SSH",
    )
    remote_subparsers = remote_parser.add_subparsers(dest="remote_subcommand")

    # remote add
    add_parser = remote_subparsers.add_parser("add", help="Add a remote Linux machine configuration")
    add_parser.add_argument("id", help="Device identifier (e.g. srv1)")
    add_parser.add_argument("hostname", help="Remote host IP or domain name")
    add_parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    add_parser.add_argument("--username", "-u", type=str, default=None, help="SSH username")
    add_parser.add_argument("--name", "-n", type=str, default=None, help="Display name")
    add_parser.add_argument("--key", "-k", type=str, default=None, help="Path to private SSH key")

    # remote list
    remote_subparsers.add_parser("list", help="List configured remote machines")

    # remote remove
    rm_parser = remote_subparsers.add_parser("remove", help="Remove a remote machine configuration")
    rm_parser.add_argument("id", help="Device identifier to remove")

    # remote status
    status_parser = remote_subparsers.add_parser("status", help="Check status of a remote machine")
    status_parser.add_argument("id", help="Device identifier to inspect")

    args, unknown = parser.parse_known_args(argv)

    if args.subcommand == "remote":
        if args.remote_subcommand is None:
            print(
                "ServiceDeck 2.0 remote trusted management is part of Phase 2 (SSH tunnels and persistent authorization).",
                file=sys.stderr,
            )
            print("Run 'servicedeck remote --help' for available commands.", file=sys.stderr)
            return 0

        from servicedeck.backend.remote.device_config import DeviceConfigManager, RemoteDevice

        cfg_mgr = DeviceConfigManager()

        if args.remote_subcommand == "list":
            devices = cfg_mgr.load_devices()
            if not devices:
                print("No remote devices configured.")
                return 0
            print(f"{'ID':<15} {'HOSTNAME':<25} {'PORT':<8} {'USER':<15} {'NAME'}")
            print("-" * 75)
            for d in devices:
                print(
                    f"{d.id:<15} {d.hostname:<25} {d.port:<8} {d.username or '':<15} {d.display_name}"
                )
            return 0

        if args.remote_subcommand == "add":
            device = RemoteDevice(
                id=args.id,
                display_name=args.name or args.id,
                hostname=args.hostname,
                port=args.port,
                username=args.username,
                ssh_key_path=args.key,
            )
            cfg_mgr.save_device(device)
            print(f"Device '{device.id}' ({device.hostname}:{device.port}) added successfully.")
            return 0

        if args.remote_subcommand == "remove":
            removed = cfg_mgr.remove_device(args.id)
            if removed:
                print(f"Device '{args.id}' removed successfully.")
                return 0
            print(f"Device '{args.id}' not found.", file=sys.stderr)
            return 1

        if args.remote_subcommand == "status":
            device = cfg_mgr.get_device(args.id)
            if device is None:
                print(f"Device '{args.id}' not found.", file=sys.stderr)
                return 1
            print(f"Device ID:     {device.id}")
            print(f"Display Name:  {device.display_name}")
            print(f"Host:          {device.hostname}:{device.port}")
            print(f"Username:      {device.username or 'default'}")
            print(f"Key Path:      {device.ssh_key_path or 'ssh-agent'}")
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
