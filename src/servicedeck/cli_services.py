"""Service commands of the ``servicedeck`` CLI: list, status, start/stop/..., logs.

They talk to a running backend through :class:`ServiceDeckClient`, so ``--host`` reaches
remote devices exactly like the GUI does. ``--json`` gives machine-readable output.
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import getpass
import json
import os
import shutil
import sys
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from servicedeck.api_client import ServiceDeckClient
    from servicedeck.api_client.models.service import Service

DEFAULT_URL = "http://127.0.0.1:8000"

#: Lifecycle actions: CLI verb -> (client method name, past tense for messages).
ACTIONS: dict[str, tuple[str, str]] = {
    "start": ("start_service", "started"),
    "stop": ("stop_service", "stopped"),
    "restart": ("restart_service", "restarted"),
    "reload": ("reload_service", "reloaded"),
    "enable": ("enable_service", "enabled"),
    "disable": ("disable_service", "disabled"),
    "mask": ("mask_service", "masked"),
    "unmask": ("unmask_service", "unmasked"),
}

COMMANDS = frozenset({"list", "status", "logs", *ACTIONS})

# Exit codes for ``status``, following ``systemctl status``.
EXIT_INACTIVE = 3
EXIT_NOT_FOUND = 4

_ELEVATION_REQUIRED = "RemoteElevationRequiredError"
_SUDO_AUTH_ERROR = "RemoteSudoAuthError"


# --- Argument parsing ---


def _add_target_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        metavar="DEVICE",
        default=None,
        help="Remote device id (see 'servicedeck remote list'); default: this machine",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--scope",
        choices=["user", "system"],
        default="user",
        help="Service scope (default: user)",
    )
    scope.add_argument(
        "--system",
        dest="scope",
        action="store_const",
        const="system",
        help="Same as --scope system",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("SERVICEDECK_BACKEND_URL", DEFAULT_URL),
        help=f"Backend URL (default: $SERVICEDECK_BACKEND_URL or {DEFAULT_URL})",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")


def add_service_parsers(subparsers: Any) -> None:
    """Register the service subcommands on the top-level CLI parser."""
    list_parser = subparsers.add_parser("list", help="List services")
    list_parser.add_argument(
        "pattern", nargs="?", default=None, help="Only names matching this glob (e.g. 'ng*')"
    )
    state = list_parser.add_mutually_exclusive_group()
    state.add_argument("--failed", action="store_true", help="Only failed services")
    state.add_argument("--active", action="store_true", help="Only active services")
    _add_target_options(list_parser)

    status_parser = subparsers.add_parser(
        "status",
        help="Show a service's state, resources and recent logs",
        description="Exit status: 0 active, 3 not active, 4 no such service, 1 error.",
    )
    status_parser.add_argument("name", help="Service name (the .service suffix is optional)")
    status_parser.add_argument(
        "-n", "--lines", type=int, default=10, help="Recent log lines to show (default: 10)"
    )
    _add_target_options(status_parser)

    for verb in ACTIONS:
        action_parser = subparsers.add_parser(verb, help=f"{verb.capitalize()} service(s)")
        action_parser.add_argument("names", nargs="+", metavar="name", help="Service name(s)")
        _add_target_options(action_parser)

    logs_parser = subparsers.add_parser("logs", help="Show a service's journal")
    logs_parser.add_argument("name", help="Service name")
    logs_parser.add_argument(
        "-n", "--lines", type=int, default=200, help="Number of lines (default: 200)"
    )
    logs_parser.add_argument(
        "-f", "--follow", action="store_true", help="Keep printing new lines (Ctrl-C to stop)"
    )
    _add_target_options(logs_parser)


# --- Output helpers ---


class _Style:
    """ANSI colors, only when stdout is a terminal and NO_COLOR is unset."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def state(self, text: str, active_state: str) -> str:
        state = active_state.lower()
        if state == "active":
            return self._wrap("32", text)
        if state == "failed":
            return self._wrap("31;1", text)
        if state in ("activating", "deactivating", "reloading"):
            return self._wrap("33", text)
        return text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)


def _style() -> _Style:
    return _Style(sys.stdout.isatty() and "NO_COLOR" not in os.environ)


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _as_dict(obj: Any) -> Any:
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj


def _print_table(services: list[Service]) -> None:
    style = _style()
    headers = ("UNIT", "ACTIVE", "SUB", "ENABLED", "DESCRIPTION")
    rows = [
        (s.name, s.active_state, s.sub_state, s.unit_file_state, s.description) for s in services
    ]
    widths = [max([len(h), *(len(r[i]) for r in rows)]) for i, h in enumerate(headers[:4])]
    term_width = shutil.get_terminal_size((120, 24)).columns
    desc_width = max(10, term_width - sum(widths) - 2 * len(widths))

    def line(cells: tuple[str, ...], active_state: str | None = None) -> str:
        padded = [cell.ljust(widths[i]) for i, cell in enumerate(cells[:4])]
        if active_state is not None:
            padded[1] = style.state(padded[1], active_state)
        desc = cells[4]
        if len(desc) > desc_width:
            desc = desc[: desc_width - 1] + "…"
        return "  ".join([*padded, desc]).rstrip()

    print(style.bold(line(headers)))
    for row in rows:
        print(line(row, active_state=row[1]))
    print(f"\n{len(rows)} service(s)")


def _format_timestamp(usec: int | None) -> str | None:
    if not usec:
        return None
    try:
        return datetime.fromtimestamp(usec / 1_000_000).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return None


def _format_bytes(value: int | None) -> str | None:
    if value is None:
        return None
    size = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return None


# --- Running commands ---


def _call_with_elevation[T](
    client: ServiceDeckClient, args: argparse.Namespace, call: Callable[[], T]
) -> T:
    """Run ``call``; if a remote host needs administrator access, get it and retry once.

    Passwordless sudo is tried first; otherwise the sudo password is asked for on the
    terminal (it goes only to the local backend, which uses it once and never stores it).
    """
    from servicedeck.api_client.exceptions import ServiceDeckHTTPError

    try:
        return call()
    except ServiceDeckHTTPError as exc:
        if args.host is None or exc.error_type != _ELEVATION_REQUIRED:
            raise
    _elevate(client, args.host)
    return call()


def _elevate(client: ServiceDeckClient, device_id: str) -> None:
    from servicedeck.api_client.exceptions import ServiceDeckHTTPError

    try:
        client.elevate_device(device_id, password=None)
        return
    except ServiceDeckHTTPError as exc:
        if exc.error_type != _SUDO_AUTH_ERROR or not sys.stdin.isatty():
            raise
    for attempt in range(3):
        password = getpass.getpass(f"[sudo] password on '{device_id}' (used once, not saved): ")
        if not password:
            raise KeyboardInterrupt
        try:
            client.elevate_device(device_id, password=password)
            return
        except ServiceDeckHTTPError as exc:
            if exc.error_type != _SUDO_AUTH_ERROR or attempt == 2:
                raise
            print("Sorry, try again.", file=sys.stderr)
        finally:
            del password


def _cmd_list(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    services = _call_with_elevation(
        client, args, lambda: client.list_services(scope=args.scope, device_id=args.host)
    )
    if args.pattern:
        pattern = args.pattern
        services = [
            s
            for s in services
            if fnmatch.fnmatch(s.name, pattern) or fnmatch.fnmatch(s.name, f"{pattern}.service")
        ]
    if args.failed:
        services = [s for s in services if s.is_failed]
    elif args.active:
        services = [s for s in services if s.is_active]

    if args.json:
        _print_json([_as_dict(s) for s in services])
    elif services:
        _print_table(services)
    else:
        print("No services match.")
    return 0


def _cmd_status(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    from servicedeck.api_client.exceptions import ServiceDeckAPIError, ServiceNotFoundError

    scope, host = args.scope, args.host
    try:
        service = _call_with_elevation(
            client, args, lambda: client.get_service(args.name, scope=scope, device_id=host)
        )
    except ServiceNotFoundError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return EXIT_NOT_FOUND

    def optional(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except ServiceDeckAPIError:
            return None

    unit_file = optional(lambda: client.get_unit_file(service.name, scope=scope, device_id=host))
    resources = optional(lambda: client.get_resources(service.name, scope=scope, device_id=host))
    logs = (
        optional(
            lambda: client.get_logs(service.name, lines=args.lines, scope=scope, device_id=host)
        )
        if args.lines > 0
        else None
    )
    exit_code = 0 if service.is_active else EXIT_INACTIVE

    if args.json:
        _print_json(
            {
                "service": _as_dict(service),
                "unit_file_path": unit_file.fragment_path if unit_file else None,
                "resources": _as_dict(resources) if resources else None,
                "logs": logs.logs if logs else None,
            }
        )
        return exit_code

    style = _style()
    title = f"{service.name} - {service.description}" if service.description else service.name
    print(style.state("●", service.active_state), style.bold(title))
    path = unit_file.fragment_path if unit_file else None
    loaded = f"{service.load_state} ({path or 'no unit file'}; {service.unit_file_state})"
    active = f"{service.active_state} ({service.sub_state})"
    rows: list[tuple[str, str]] = [
        ("Loaded", loaded),
        ("Active", style.state(active, service.active_state)),
        ("Scope", f"{service.scope}" + (f" on {host}" if host else "")),
    ]
    if resources is not None and service.is_active:
        since = _format_timestamp(resources.active_enter_timestamp)
        if since:
            rows[1] = ("Active", f"{rows[1][1]} since {since}")
        if resources.main_pid:
            rows.append(("Main PID", str(resources.main_pid)))
        if resources.tasks_current is not None:
            rows.append(("Tasks", str(resources.tasks_current)))
        memory = _format_bytes(resources.memory_current_bytes)
        if memory:
            rows.append(("Memory", memory))
        if resources.cpu_usage_nsec is not None:
            rows.append(("CPU", f"{resources.cpu_usage_nsec / 1e9:.3f}s"))
    for label, value in rows:
        print(f"{label:>10}: {value}")
    if logs and logs.logs.strip():
        print()
        print(logs.logs.rstrip("\n"))
    return exit_code


def _cmd_action(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    from servicedeck.api_client.exceptions import ServiceDeckAPIError

    method_name, past = ACTIONS[args.subcommand]
    method = getattr(client, method_name)
    results: list[dict[str, Any]] = []
    failures = 0
    for name in args.names:
        try:
            result = _call_with_elevation(
                client,
                args,
                lambda name=name: method(name, scope=args.scope, device_id=args.host),
            )
            results.append({"service": name, "success": True, "message": result.message})
            if not args.json:
                print(f"{name}: {past}")
        except ServiceDeckAPIError as exc:
            failures += 1
            results.append({"service": name, "success": False, "message": exc.message})
            if not args.json:
                print(f"error: {name}: {exc.message}", file=sys.stderr)
    if args.json:
        _print_json(results)
    return 1 if failures else 0


def _cmd_logs(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    lines = max(0, args.lines)
    if not args.follow:
        logs = _call_with_elevation(
            client,
            args,
            lambda: client.get_logs(
                args.name, lines=max(1, lines), scope=args.scope, device_id=args.host
            ),
        )
        if args.json:
            _print_json(_as_dict(logs))
        else:
            sys.stdout.write(
                logs.logs if logs.logs.endswith("\n") or not logs.logs else logs.logs + "\n"
            )
        return 0

    stream = _call_with_elevation(
        client,
        args,
        lambda: client.follow_logs(args.name, lines=lines, scope=args.scope, device_id=args.host),
    )
    try:
        for line in stream:
            print(json.dumps({"line": line}) if args.json else line, flush=True)
    finally:
        stream.close()
    return 0


_HANDLERS: dict[str, Callable[[ServiceDeckClient, argparse.Namespace], int]] = {
    "list": _cmd_list,
    "status": _cmd_status,
    "logs": _cmd_logs,
    **dict.fromkeys(ACTIONS, _cmd_action),
}


def run_service_command(
    args: argparse.Namespace, client_factory: Callable[[str], ServiceDeckClient] | None = None
) -> int:
    """Run a parsed service subcommand; returns the process exit code."""
    from servicedeck.api_client import ServiceDeckClient
    from servicedeck.api_client.exceptions import (
        ServiceDeckAPIError,
        ServiceDeckConnectionError,
    )

    factory = client_factory or (lambda url: ServiceDeckClient(base_url=url))
    client = factory(args.url)
    try:
        return _HANDLERS[args.subcommand](client, args)
    except ServiceDeckConnectionError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        print("Is the backend running? Start it with 'servicedeck backend'.", file=sys.stderr)
        return 1
    except ServiceDeckAPIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        client.close()


__all__ = ["ACTIONS", "COMMANDS", "add_service_parsers", "run_service_command"]
