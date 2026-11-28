"""Local administrator session: the real bundled agent behind a fake ``sudo``, and idle drop."""

import asyncio
import os
import stat
import sys
from pathlib import Path

import pytest

from servicedeck.backend.core.local_admin import LocalAdminSession
from servicedeck.backend.exceptions import (
    LocalElevationRequiredError,
    RemoteSudoAuthError,
    ServiceOperationError,
)
from servicedeck.backend.remote.privileged import LocalPrivilegedAgent
from servicedeck.remote.models import HelloMessage, RequestMessage, ResponseMessage

PASSWORD = "local-pass"

# Mimics the sudo options ServiceDeck uses (-k -S -p PROMPT | -n), then runs the command
# as the current user. Wrong passwords print sudo's real message.
FAKE_SUDO = f"""#!/bin/sh
prompt=""
mode=""
while [ $# -gt 0 ]; do
  case "$1" in
    -k) shift ;;
    -S) mode=stdin; shift ;;
    -n) mode=noninteractive; shift ;;
    -p) prompt="$2"; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
if [ "$mode" = noninteractive ]; then
  echo "sudo: a password is required" >&2
  exit 1
fi
printf '%s' "$prompt" >&2
IFS= read -r pw
if [ "$pw" != "{PASSWORD}" ]; then
  echo "sudo: 1 incorrect password attempt" >&2
  exit 1
fi
exec "$@"
"""


@pytest.fixture
def fake_sudo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "bin" / "sudo"
    script.parent.mkdir()
    script.write_text(FAKE_SUDO)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{script.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    return script


def _agent() -> LocalPrivilegedAgent:
    agent = LocalPrivilegedAgent(python=sys.executable)
    # The fake sudo does not change user; accept our own uid instead of root's.
    agent.required_uid = os.getuid()
    return agent


async def test_bundled_agent_starts_through_sudo_and_answers(fake_sudo: Path) -> None:
    agent = _agent()
    try:
        hello = await agent.start(PASSWORD, timeout=20)
        assert hello.uid == os.getuid()
        assert agent.is_alive

        # A syntax error is answered by the agent without touching D-Bus.
        response = await agent.send_request(
            RequestMessage(
                id=1,
                method="service.override.write",
                params={"name": "demo", "content": "Nice=5", "scope": "system"},
            ),
            timeout=20,
        )
        assert not response.success
        assert response.error is not None
        assert response.error.code == "SERVICE_OPERATION_FAILED"
        assert "inside a section" in response.error.message
    finally:
        await agent.close()
    assert not agent.is_alive


async def test_wrong_password_is_reported_without_the_password(fake_sudo: Path) -> None:
    agent = _agent()
    with pytest.raises(RemoteSudoAuthError) as info:
        await agent.start("nope", timeout=20)
    assert "nope" not in str(info.value)
    assert "nope" not in repr(info.value.details)
    assert not agent.is_alive


async def test_passwordless_attempt_reports_password_required(fake_sudo: Path) -> None:
    agent = _agent()
    with pytest.raises(RemoteSudoAuthError) as info:
        await agent.start(None, timeout=20)
    assert info.value.details["password_required"] is True


# --- Session behavior with a scripted agent ---


class ScriptedAgent:
    def __init__(self) -> None:
        self.alive = False
        self.closed = 0

    @property
    def is_alive(self) -> bool:
        return self.alive

    async def start(self, password: str | None, timeout: float = 30.0) -> HelloMessage:
        self.alive = True
        return HelloMessage(uid=0)

    async def send_request(self, request: RequestMessage, timeout: float = 30.0) -> ResponseMessage:
        return ResponseMessage(id=request.id, success=True, result={"path": "/etc/x"})

    async def close(self) -> None:
        self.alive = False
        self.closed += 1


async def test_idle_session_is_dropped() -> None:
    agent = ScriptedAgent()
    session = LocalAdminSession(idle_timeout=0.05, agent_factory=lambda: agent)
    await session.elevate(None)
    assert session.is_elevated

    for _ in range(50):
        if not session.is_elevated:
            break
        await asyncio.sleep(0.02)
    assert not session.is_elevated
    assert agent.closed == 1
    with pytest.raises(LocalElevationRequiredError):
        await session.request("service.create", {"name": "x"})


async def test_activity_keeps_session_alive() -> None:
    agent = ScriptedAgent()
    session = LocalAdminSession(idle_timeout=0.15, agent_factory=lambda: agent)
    await session.elevate(None)
    for _ in range(5):
        await asyncio.sleep(0.05)
        await session.request("service.create", {"name": "x"})
    assert session.is_elevated
    await session.close()
    assert not session.is_elevated


async def test_run_system_write_uses_local_call_for_user_scope() -> None:
    session = LocalAdminSession(idle_timeout=0, agent_factory=ScriptedAgent)
    await session.elevate(None)

    async def local_call() -> str:
        return "local"

    assert await session.run_system_write("user", "m", {}, local_call, lambda _: "root") == "local"
    assert await session.run_system_write("system", "m", {}, local_call, lambda _: "root") == "root"
    await session.close()


async def test_run_system_write_passes_through_other_errors() -> None:
    session = LocalAdminSession(idle_timeout=0, agent_factory=ScriptedAgent)

    async def local_call() -> str:
        raise ServiceOperationError("x.service", "edit", "bad")

    with pytest.raises(ServiceOperationError):
        await session.run_system_write("system", "m", {}, local_call, str)
