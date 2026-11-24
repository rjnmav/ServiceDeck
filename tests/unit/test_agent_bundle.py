"""Tests for the self-contained remote agent bundle (beiboot-style bootstrap).

The key guarantee: the bundle runs under ``python -I -S`` — no site-packages, so neither
the installed servicedeck nor pydantic/dbus_fast are importable — exactly like a bare
remote host that has only ``python3``.
"""

import asyncio
import base64
import os
import re
import shlex
import subprocess
import sys
import zlib

import pytest

from servicedeck.backend.remote import bundle
from servicedeck.backend.remote.bundle import (
    PYTHON_TOO_OLD_MARKER,
    build_payload,
    collect_agent_sources,
    get_agent_payload,
    stage1_command,
    stage1_source,
)
from servicedeck.remote.models import HelloMessage
from servicedeck.remote.protocol import read_message

_FORBIDDEN_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(pydantic|pydantic_settings|pydantic_core|fastapi|PySide6|asyncssh|httpx)\b",
    re.MULTILINE,
)


def _run_stage1(payload: bytes, stdin_extra: bytes = b"", timeout: float = 30.0):
    """Run stage 1 the way the remote shell would, but with site-packages disabled."""
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", stage1_source(), str(len(payload))],
        input=payload + stdin_extra,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def test_sources_have_no_compiled_only_dependencies() -> None:
    sources = collect_agent_sources()
    assert "servicedeck/remote_agent/main.py" in sources
    assert "dbus_fast/aio/__init__.py" in sources
    assert not any(path.startswith("dbus_fast/glib/") for path in sources)
    offenders = {path for path, src in sources.items() if _FORBIDDEN_IMPORT.search(src)}
    assert offenders == set()


def test_bundle_imports_agent_without_site_packages() -> None:
    payload = build_payload(
        entrypoint=(
            "import servicedeck, servicedeck.remote_agent.main, dbus_fast.aio\n"
            "assert servicedeck.__spec__.origin.startswith('<servicedeck-agent>/')\n"
            "try:\n"
            "    import pydantic\n"
            "except ImportError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('pydantic unexpectedly importable')\n"
            "print('BUNDLE-OK')\n"
        )
    )
    result = _run_stage1(payload.data)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode().strip() == "BUNDLE-OK"


def test_stage1_reads_exactly_payload_length() -> None:
    """Bytes after the payload must stay on stdin for the protocol (no over-read)."""
    payload = build_payload(
        entrypoint="import os\nprint(os.read(0, 100).decode(), end='')\n",
    )
    result = _run_stage1(payload.data, stdin_extra=b"FIRST-FRAME")
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode() == "FIRST-FRAME"


def test_stage1_reports_truncated_payload() -> None:
    data = get_agent_payload().data
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", stage1_source(), str(len(data))],
        input=data[:100],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert b"bootstrap payload truncated (100/" in result.stderr


def test_stage1_rejects_old_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, "MIN_REMOTE_PYTHON", (99, 0))
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", stage1_source(), "0"],
        input=b"",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert PYTHON_TOO_OLD_MARKER.encode() in result.stderr
    assert b">= 99.0 required" in result.stderr


def test_stage1_command_is_single_shell_safe_line() -> None:
    cmd = stage1_command(1234)
    assert "\n" not in cmd
    argv = shlex.split(cmd)
    assert argv[:3] == ["exec", "python3", "-c"]
    assert argv[4] == "1234"
    encoded = re.fullmatch(
        r'import base64;exec\(base64\.b64decode\("([A-Za-z0-9+/=]+)"\)\)', argv[3]
    )
    assert encoded is not None
    assert base64.b64decode(encoded.group(1)).decode() == stage1_source()


def test_payload_is_cached_and_hashed() -> None:
    first = get_agent_payload()
    assert get_agent_payload() is first
    assert len(first.sha256) == 64
    assert zlib.decompress(first.data).decode().startswith("SOURCES = {")


def _user_bus_available() -> bool:
    return bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) or os.path.exists(
        f"/run/user/{os.getuid()}/bus"
    )


@pytest.mark.skipif(not _user_bus_available(), reason="No user D-Bus session available")
async def test_bundled_agent_sends_hello() -> None:
    """Full agent from the bundle completes the protocol handshake over a pipe."""
    payload = get_agent_payload()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-S",
        "-c",
        stage1_source(),
        str(len(payload.data)),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(payload.data)
        await proc.stdin.drain()
        message = await asyncio.wait_for(read_message(proc.stdout), timeout=15)
        assert isinstance(message, HelloMessage)
        assert message.uid == os.getuid()
    finally:
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()
