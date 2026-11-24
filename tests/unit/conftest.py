"""Unit-test isolation for SSH onboarding state.

Keeps unit tests from touching the real ``~/.config/servicedeck`` (known_hosts, login
key) or ``~/.ssh/known_hosts``, and from making network connections to read host keys.
"""

from pathlib import Path

import asyncssh
import pytest

from servicedeck.backend.remote import keys, known_hosts


@pytest.fixture(autouse=True)
def _isolate_ssh_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "servicedeck-state"
    monkeypatch.setattr(known_hosts, "DEFAULT_KNOWN_HOSTS_PATH", state / "known_hosts")
    monkeypatch.setattr(known_hosts, "OPENSSH_KNOWN_HOSTS_PATH", state / "openssh_known_hosts")
    monkeypatch.setattr(keys, "DEFAULT_KEY_DIR", state / "ssh")

    async def _no_network(*_args: object, **_kwargs: object) -> None:
        raise OSError("network access disabled in unit tests")

    monkeypatch.setattr(asyncssh, "get_server_host_key", _no_network)
