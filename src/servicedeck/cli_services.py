"""Service commands of the ``servicedeck`` CLI: list, status, start/stop/..., logs, and
unit files: cat, edit (drop-in overrides), revert, create.

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
import shlex
import shutil
import subprocess
import sys
import tempfile
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

UNIT_FILE_COMMANDS = frozenset({"cat", "edit", "revert", "create"})

COMMANDS = frozenset({"list", "status", "logs", *ACTIONS, *UNIT_FILE_COMMANDS})

# Exit codes for ``status``, following ``systemctl status``.
EXIT_INACTIVE = 3
EXIT_NOT_FOUND = 4

_ELEVATION_REQUIRED = "RemoteElevationRequiredError"
_LOCAL_ELEVATION_REQUIRED = "LocalElevationRequiredError"
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

    cat_parser = subparsers.add_parser(
        "cat", help="Show a service's unit file and drop-ins (like 'systemctl cat')"
    )
    cat_parser.add_argument("name", help="Service name")
    _add_target_options(cat_parser)

    edit_parser = subparsers.add_parser(
        "edit",
        help="Edit a service through a drop-in override (like 'systemctl edit')",
        description="Opens $VISUAL/$EDITOR on <unit>.d/override.conf. systemd is reloaded "
        "afterwards; if the unit no longer loads, the previous override is restored. Saving "
        "only comments removes the override. System units ask for the sudo password.",
    )
    edit_parser.add_argument("name", help="Service name")
    edit_parser.add_argument(
        "--drop-in",
        default="override.conf",
        metavar="FILE",
        help="Drop-in file name in <unit>.d/ (default: override.conf)",
    )
    edit_parser.add_argument(
        "--stdin", action="store_true", help="Read the new drop-in content from stdin"
    )
    _add_target_options(edit_parser)

    revert_parser = subparsers.add_parser(
        "revert",
        help="Remove a service's drop-in overrides (back to the vendor unit)",
        description="Deletes the *.conf files in the writable <unit>.d/ directory and "
        "reloads systemd. Vendor and runtime drop-ins are kept; the unit is not unmasked.",
    )
    revert_parser.add_argument("name", help="Service name")
    revert_parser.add_argument("-y", "--yes", action="store_true", help="Do not ask to confirm")
    _add_target_options(revert_parser)

    create_parser = subparsers.add_parser(
        "create",
        help="Install a new service unit file",
        description="Writes ~/.config/systemd/user/NAME (user) or /etc/systemd/system/NAME "
        "(system, asks for the sudo password) and reloads systemd.",
    )
    create_parser.add_argument("name", help="Service name")
    create_parser.add_argument(
        "-f",
        "--file",
        required=True,
        metavar="PATH",
        help="Unit file to install ('-' reads stdin)",
    )
    create_parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing unit file"
    )
    _add_target_options(create_parser)


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
    """Run ``call``; if administrator access is needed, get it and retry once.

    Remote hosts get a root agent on the device; this computer gets a local root agent
    (for system unit files). Passwordless sudo is tried first; otherwise the sudo password
    is asked for on the terminal. It goes only to the local backend, which uses it once and
    never stores it.
    """
    from servicedeck.api_client.exceptions import ServiceDeckHTTPError

    try:
        return call()
    except ServiceDeckHTTPError as exc:
        if args.host is not None and exc.error_type == _ELEVATION_REQUIRED:
            _elevate(client, args.host)
        elif args.host is None and exc.error_type == _LOCAL_ELEVATION_REQUIRED:
            _elevate_local(client)
            # Never leave the backend running as root after a script's command.
            args.drop_local_elevation = True
        else:
            raise
    return call()


def _can_prompt() -> bool:
    """True if a password can be asked for (stdin, or the controlling terminal)."""
    if sys.stdin.isatty():
        return True
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return False
    os.close(fd)
    return True


def _sudo_with_password(elevate: Callable[[str | None], Any], prompt: str) -> None:
    from servicedeck.api_client.exceptions import ServiceDeckHTTPError

    try:
        elevate(None)
        return
    except ServiceDeckHTTPError as exc:
        if exc.error_type != _SUDO_AUTH_ERROR or not _can_prompt():
            raise
    for attempt in range(3):
        password = getpass.getpass(prompt)
        if not password:
            raise KeyboardInterrupt
        try:
            elevate(password)
            return
        except ServiceDeckHTTPError as exc:
            if exc.error_type != _SUDO_AUTH_ERROR or attempt == 2:
                raise
            print("Sorry, try again.", file=sys.stderr)
        finally:
            del password


def _elevate(client: ServiceDeckClient, device_id: str) -> None:
    _sudo_with_password(
        lambda password: client.elevate_device(device_id, password=password),
        f"[sudo] password on '{device_id}' (used once, not saved): ",
    )


def _elevate_local(client: ServiceDeckClient) -> None:
    _sudo_with_password(
        lambda password: client.elevate_local(password=password),
        "[sudo] password for this computer (used once, not saved): ",
    )


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


def _health_rows(service: Any, resources: Any, style: _Style) -> list[tuple[str, str]]:
    """Restart count, last exit and failure time, like ``systemctl status`` shows them."""
    from servicedeck.api_client.models.service import format_ago

    rows: list[tuple[str, str]] = []
    if service.is_failed:
        failed_for = resources.failed_for_seconds()
        when = _format_timestamp(resources.state_change_timestamp)
        detail = f"Result: {resources.result}" if resources.result else "failed"
        if when and failed_for is not None:
            detail += f"; since {when}, {format_ago(failed_for)} ago"
        rows.append(("Failed", style.state(detail, "failed")))
    last_exit = resources.last_exit
    if last_exit and (not service.is_active or (resources.n_restarts or 0) > 0):
        rows.append(("Last exit", last_exit))
    if resources.n_restarts is not None:
        restarts = str(resources.n_restarts)
        rows.append(
            ("Restarts", style.state(restarts, "activating") if resources.n_restarts else restarts)
        )
    return rows


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
    if resources is not None:
        rows.extend(_health_rows(service, resources, style))
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


# --- Unit files ---

_EDIT_MARK = "###"


def _editor_command() -> list[str]:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return shlex.split(editor)
    for candidate in ("nano", "vi"):
        if shutil.which(candidate):
            return [candidate]
    raise SystemExit("error: set $EDITOR (or $VISUAL) to choose an editor, or use --stdin")


def _edit_template(path: str, current: str, unit: Any) -> str:
    reference = "\n".join(f"{_EDIT_MARK} {line}".rstrip() for line in unit.content.splitlines())
    header = (
        f"{_EDIT_MARK} Editing {path}\n"
        f"{_EDIT_MARK} Lines starting with '{_EDIT_MARK}' are ignored. Saving only comments "
        "removes this override.\n"
        f"{_EDIT_MARK} Reset a list setting before adding to it, e.g. 'ExecStart=' then "
        "'ExecStart=/new/command'.\n"
        f"{_EDIT_MARK}\n"
        f"{_EDIT_MARK} Current unit file: {unit.fragment_path or '(none on disk)'}\n"
        f"{reference}\n"
        f"{_EDIT_MARK} --- override below ---\n"
    )
    return header + (current if current else "[Service]\n")


def _strip_edit_marks(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.startswith(_EDIT_MARK)]
    return "\n".join(lines).strip("\n") + ("\n" if any(line.strip() for line in lines) else "")


def _run_editor(initial: str, suffix: str) -> str | None:
    """Edit ``initial`` in the user's editor; ``None`` if the editor failed."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=suffix, prefix="servicedeck-", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(initial)
        path = handle.name
    try:
        result = subprocess.run([*_editor_command(), path], check=False)
        if result.returncode != 0:
            return None
        with open(path, encoding="utf-8") as edited:
            return edited.read()
    finally:
        os.unlink(path)


def _cmd_cat(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    unit = _call_with_elevation(
        client, args, lambda: client.get_unit_file(args.name, scope=args.scope, device_id=args.host)
    )
    if args.json:
        _print_json(_as_dict(unit))
        return 0
    style = _style()
    print(style.bold(f"# {unit.fragment_path or '(no unit file on disk)'}"))
    print(unit.content.rstrip())
    for drop_in in unit.drop_ins:
        print()
        print(style.bold(f"# {drop_in.path}"))
        print(drop_in.content.rstrip())
    if unit.need_daemon_reload:
        print(
            "\nwarning: unit files changed on disk; systemd has not been reloaded.", file=sys.stderr
        )
    return 0


def _cmd_edit(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    from servicedeck.backend.models.unit_syntax import check_unit_text

    scope, host = args.scope, args.host
    unit = _call_with_elevation(
        client, args, lambda: client.get_unit_file(args.name, scope=scope, device_id=host)
    )
    directory = (unit.override_path or "").rsplit("/", 1)[0]
    path = f"{directory}/{args.drop_in}" if directory else args.drop_in
    current = next((d.content for d in unit.drop_ins if d.path == path), "")

    if args.stdin:
        content = sys.stdin.read()
    else:
        if not sys.stdin.isatty():
            print("error: no terminal for an editor; use --stdin", file=sys.stderr)
            return 1
        text = _edit_template(path, current, unit)
        unchanged = _strip_edit_marks(text)
        while True:
            edited = _run_editor(text, suffix=".conf")
            if edited is None:
                print("Editor failed; nothing was changed.", file=sys.stderr)
                return 1
            content = _strip_edit_marks(edited)
            report = check_unit_text(content, drop_in=True)
            if report.ok:
                break
            for error in report.errors:
                print(f"error: {error}", file=sys.stderr)
            answer = input("[e]dit again or [a]bort? ").strip().lower()
            if not answer.startswith("e"):
                print("Aborted; nothing was changed.", file=sys.stderr)
                return 1
            text = edited
        if content == unchanged or content.strip() == current.strip():
            print("No changes.")
            return 0

    result = _call_with_elevation(
        client,
        args,
        lambda: client.write_override(
            args.name, content, scope=scope, drop_in=args.drop_in, device_id=host
        ),
    )
    if args.json:
        _print_json(_as_dict(result))
        return 0
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if result.removed:
        print(f"Removed {result.path}; systemd reloaded.")
    else:
        print(f"Wrote {result.path}; systemd reloaded ({result.load_state}).")
    return 0


def _cmd_revert(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    scope, host = args.scope, args.host
    unit = _call_with_elevation(
        client, args, lambda: client.get_unit_file(args.name, scope=scope, device_id=host)
    )
    files = unit.editable_drop_ins
    if not files:
        print(f"{unit.service} has no overrides to remove.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("error: refusing to delete without a terminal; pass --yes", file=sys.stderr)
            return 1
        print("This deletes:")
        for drop_in in files:
            print(f"  {drop_in.path}")
        if not input("Continue? [y/N] ").strip().lower().startswith("y"):
            print("Aborted; nothing was changed.")
            return 1
    result = _call_with_elevation(
        client, args, lambda: client.revert_overrides(args.name, scope=scope, device_id=host)
    )
    if args.json:
        _print_json(_as_dict(result))
        return 0
    for path in result.removed_paths:
        print(f"Removed {path}")
    print(f"{result.service} uses its vendor configuration again; systemd reloaded.")
    return 0


def _cmd_create(client: ServiceDeckClient, args: argparse.Namespace) -> int:
    if args.file == "-":
        content = sys.stdin.read()
    else:
        try:
            with open(args.file, encoding="utf-8") as handle:
                content = handle.read()
        except OSError as exc:
            print(f"error: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
            return 1
    created = _call_with_elevation(
        client,
        args,
        lambda: client.create_service(
            args.name,
            content,
            scope=args.scope,
            overwrite=args.overwrite,
            device_id=args.host,
        ),
    )
    if args.json:
        _print_json(_as_dict(created))
    else:
        print(f"Created {created.path}; systemd reloaded.")
    return 0


_HANDLERS: dict[str, Callable[[ServiceDeckClient, argparse.Namespace], int]] = {
    "list": _cmd_list,
    "status": _cmd_status,
    "logs": _cmd_logs,
    "cat": _cmd_cat,
    "edit": _cmd_edit,
    "revert": _cmd_revert,
    "create": _cmd_create,
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
        if getattr(args, "drop_local_elevation", False):
            try:
                client.drop_local_elevation()
            except (ServiceDeckAPIError, ServiceDeckConnectionError) as exc:
                print(f"warning: could not drop administrator access: {exc}", file=sys.stderr)
        client.close()


__all__ = ["ACTIONS", "COMMANDS", "add_service_parsers", "run_service_command"]
