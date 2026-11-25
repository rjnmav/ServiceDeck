"""Unified command-line interface for ServiceDeck 2.0."""

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from servicedeck.backend.remote.device_config import DeviceConfigManager, RemoteDevice


def _remote_setup_key(device: "RemoteDevice", cfg_mgr: "DeviceConfigManager") -> int:
    """Interactive TOFU host-key trust plus one-time password key installation."""
    import asyncio
    import getpass

    from servicedeck.backend.exceptions import ServiceDeckError, SSHAuthenticationError
    from servicedeck.backend.remote.key_setup import setup_key
    from servicedeck.backend.remote.known_hosts import KnownHostsStore

    known_hosts = KnownHostsStore()
    target = f"{device.username}@{device.hostname}" if device.username else device.hostname

    try:
        info = asyncio.run(known_hosts.check(device.hostname, device.port))
        if info.status == "changed":
            print(known_hosts.unverified_error(info).message, file=sys.stderr)
            return 1
        if info.status == "unknown":
            print(f"First connection to {device.hostname}:{device.port}.")
            print(f"  {info.key_type} key fingerprint: {info.fingerprint}")
            print(
                "  Verify on the remote machine: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"
            )
            if input("Trust this host key? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Host key not trusted; nothing changed.")
                return 1
            asyncio.run(known_hosts.trust(device.hostname, device.port, info.fingerprint))
            print("Host key trusted.")

        for attempt in range(3):
            password = getpass.getpass(f"Password for {target} (used once, not saved): ")
            if not password:
                print("No password entered; aborting.", file=sys.stderr)
                return 1
            try:
                result = asyncio.run(setup_key(device, password, known_hosts=known_hosts))
                break
            except SSHAuthenticationError:
                del password
                if attempt == 2:
                    raise
                print("Password not accepted, try again.", file=sys.stderr)
    except ServiceDeckError as exc:
        print(f"Key setup failed: {exc.message}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 1

    cfg_mgr.save_device(result.device)
    state = "installed" if result.added else "was already installed"
    print(f"SSH key {result.key.fingerprint} {state} on {target}.")
    print(f"'{device.id}' now connects with {result.key.private_path} (no password needed).")
    return 0


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

    # Service subcommands: list, status, start/stop/..., logs
    from servicedeck.cli_services import COMMANDS as SERVICE_COMMANDS
    from servicedeck.cli_services import add_service_parsers

    add_service_parsers(subparsers)

    # Remote subcommand
    remote_parser = subparsers.add_parser(
        "remote",
        help="Manage remote ServiceDeck instances over SSH",
    )
    remote_subparsers = remote_parser.add_subparsers(dest="remote_subcommand")

    # remote add
    add_parser = remote_subparsers.add_parser(
        "add", help="Add a remote Linux machine configuration"
    )
    add_parser.add_argument("id", help="Device identifier (e.g. srv1)")
    add_parser.add_argument("hostname", help="Remote host IP or domain name")
    add_parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    add_parser.add_argument("--username", "-u", type=str, default=None, help="SSH username")
    add_parser.add_argument("--name", "-n", type=str, default=None, help="Display name")
    add_parser.add_argument("--key", "-k", type=str, default=None, help="Path to private SSH key")
    add_parser.add_argument(
        "--agent-mode",
        choices=["bundled", "installed", "auto"],
        default="bundled",
        help="How to start the remote agent: 'bundled' streams it over SSH so nothing needs "
        "to be installed remotely (default); 'installed' runs servicedeck-remote; 'auto' "
        "uses an installed agent when present",
    )

    # remote list
    remote_subparsers.add_parser("list", help="List configured remote machines")

    # remote remove
    rm_parser = remote_subparsers.add_parser("remove", help="Remove a remote machine configuration")
    rm_parser.add_argument("id", help="Device identifier to remove")

    # remote setup-key
    setup_parser = remote_subparsers.add_parser(
        "setup-key",
        help="Trust the host key and install the ServiceDeck SSH key (asks for the password once)",
    )
    setup_parser.add_argument("id", help="Device identifier to set up")

    # remote status
    status_parser = remote_subparsers.add_parser("status", help="Check status of a remote machine")
    status_parser.add_argument("id", help="Device identifier to inspect")

    args, unknown = parser.parse_known_args(argv)

    if args.subcommand in SERVICE_COMMANDS:
        if unknown:
            parser.error(f"unrecognized arguments: {' '.join(unknown)}")
        from servicedeck.cli_services import run_service_command

        return run_service_command(args)

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
                agent_mode=args.agent_mode,
            )
            cfg_mgr.save_device(device)
            print(f"Device '{device.id}' ({device.hostname}:{device.port}) added successfully.")
            print(
                f"Run 'servicedeck remote setup-key {device.id}' to trust its host key and set "
                "up passwordless SSH login."
            )
            return 0

        if args.remote_subcommand == "setup-key":
            device = cfg_mgr.get_device(args.id)
            if device is None:
                print(f"Device '{args.id}' not found.", file=sys.stderr)
                return 1
            return _remote_setup_key(device, cfg_mgr)

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
            print(f"Agent Mode:    {device.agent_mode}")
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
