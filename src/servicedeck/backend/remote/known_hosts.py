"""SSH host-key trust store with Trust-On-First-Use (TOFU) confirmation.

ServiceDeck verifies remote host keys against two OpenSSH-format files:

* ``~/.ssh/known_hosts`` (read-only, if present) so hosts already trusted in OpenSSH work.
* ``~/.config/servicedeck/known_hosts``, the only file ServiceDeck ever writes to.

A host key is only added after the user confirmed its fingerprint, and a *changed* key
is never overwritten automatically: the connection fails closed until the stale entry
is removed by hand.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import asyncssh

from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteHostKeyChangedError,
    RemoteHostKeyUnknownError,
)

logger = logging.getLogger(__name__)

DEFAULT_KNOWN_HOSTS_PATH = Path.home() / ".config" / "servicedeck" / "known_hosts"
OPENSSH_KNOWN_HOSTS_PATH = Path.home() / ".ssh" / "known_hosts"

HostKeyStatus = Literal["trusted", "unknown", "changed"]

_HOST_KEY_FETCH_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class HostKeyInfo:
    """The key a remote SSH server presents, and how it compares to the trust store."""

    hostname: str
    port: int
    status: HostKeyStatus
    key_type: str
    fingerprint: str

    def as_details(self) -> dict[str, object]:
        return {
            "hostname": self.hostname,
            "port": self.port,
            "status": self.status,
            "key_type": self.key_type,
            "fingerprint": self.fingerprint,
        }


def known_hosts_pattern(hostname: str, port: int) -> str:
    """Return the OpenSSH known_hosts host pattern for ``hostname:port``."""
    return hostname if port == 22 else f"[{hostname}]:{port}"


class KnownHostsStore:
    """Reads trusted host keys and records newly confirmed ones."""

    def __init__(
        self,
        path: Path | None = None,
        extra_paths: list[Path] | None = None,
    ) -> None:
        self._path = path or DEFAULT_KNOWN_HOSTS_PATH
        self._extra_paths = [OPENSSH_KNOWN_HOSTS_PATH] if extra_paths is None else extra_paths

    @property
    def path(self) -> Path:
        """The ServiceDeck-owned known_hosts file."""
        return self._path

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._path.exists():
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)

    def paths(self) -> list[str]:
        """Files to verify host keys against, for ``asyncssh.connect(known_hosts=...)``.

        The ServiceDeck file is always created first, so this list is never empty: an
        empty value must never be able to disable host-key verification.
        """
        self._ensure_file()
        files = [str(p) for p in self._extra_paths if p.is_file()]
        files.append(str(self._path))
        return files

    def classify(self, hostname: str, port: int, key: asyncssh.SSHKey) -> HostKeyStatus:
        """Compare a presented host key with the trusted entries for ``hostname:port``."""
        known = asyncssh.read_known_hosts(self.paths())
        host_keys, _ca_keys, revoked_keys, *_ = known.match(hostname, "", port)
        if any(k.public_data == key.public_data for k in revoked_keys):
            return "changed"
        if any(k.public_data == key.public_data for k in host_keys):
            return "trusted"
        return "changed" if host_keys else "unknown"

    async def fetch(self, hostname: str, port: int) -> asyncssh.SSHKey:
        """Connect just far enough to learn the server's host key."""
        try:
            key = await asyncio.wait_for(
                asyncssh.get_server_host_key(hostname, port),
                timeout=_HOST_KEY_FETCH_TIMEOUT,
            )
        except (asyncssh.Error, OSError, TimeoutError) as exc:
            raise RemoteConnectionError(
                f"Could not read the SSH host key of {hostname}:{port}: {exc}",
                details={"hostname": hostname, "port": port},
            ) from exc
        if key is None:
            raise RemoteConnectionError(
                f"SSH server {hostname}:{port} did not present a host key",
                details={"hostname": hostname, "port": port},
            )
        return key

    async def check(self, hostname: str, port: int) -> HostKeyInfo:
        """Fetch the server's host key and report whether it is trusted."""
        key = await self.fetch(hostname, port)
        return HostKeyInfo(
            hostname=hostname,
            port=port,
            status=self.classify(hostname, port, key),
            key_type=key.get_algorithm(),
            fingerprint=key.get_fingerprint(),
        )

    async def trust(self, hostname: str, port: int, expected_fingerprint: str) -> HostKeyInfo:
        """Record the server's host key, but only if it matches what the user confirmed.

        Re-fetching guards against the key changing between showing the fingerprint
        and accepting it. A changed key is refused rather than replaced.
        """
        key = await self.fetch(hostname, port)
        info = HostKeyInfo(
            hostname=hostname,
            port=port,
            status=self.classify(hostname, port, key),
            key_type=key.get_algorithm(),
            fingerprint=key.get_fingerprint(),
        )
        if info.fingerprint != expected_fingerprint:
            raise RemoteHostKeyChangedError(
                f"The host key of {hostname} changed while it was being confirmed "
                f"(expected {expected_fingerprint}, got {info.fingerprint}). Not trusting it.",
                details=info.as_details(),
            )
        if info.status == "changed":
            raise RemoteHostKeyChangedError(
                changed_key_message(hostname, port, info.fingerprint, self._path),
                details=info.as_details(),
            )
        if info.status == "trusted":
            return info

        algorithm, blob = key.export_public_key().decode("ascii").split()[:2]
        line = f"{known_hosts_pattern(hostname, port)} {algorithm} {blob}\n"
        self._ensure_file()
        with open(self._path, "a", encoding="ascii") as fh:
            fh.write(line)
        logger.info(
            "Trusted SSH host key %s for %s (%s)",
            info.fingerprint,
            known_hosts_pattern(hostname, port),
            info.key_type,
        )
        return HostKeyInfo(
            hostname=hostname,
            port=port,
            status="trusted",
            key_type=info.key_type,
            fingerprint=info.fingerprint,
        )

    def unverified_error(self, info: HostKeyInfo) -> RemoteConnectionError:
        """Build the error for a connection rejected because of its host key."""
        if info.status == "unknown":
            return RemoteHostKeyUnknownError(
                f"The SSH host key of {info.hostname} is not trusted yet. "
                f"Confirm its fingerprint ({info.key_type} {info.fingerprint}) to continue.",
                details=info.as_details(),
            )
        return RemoteHostKeyChangedError(
            changed_key_message(info.hostname, info.port, info.fingerprint, self._path),
            details=info.as_details(),
        )


def changed_key_message(hostname: str, port: int, fingerprint: str, store_path: Path) -> str:
    pattern = known_hosts_pattern(hostname, port)
    return (
        f"WARNING: the SSH host key of {hostname} has CHANGED (now {fingerprint}). This can "
        "mean the machine was reinstalled, or that someone is intercepting the connection. "
        f"If you are sure the change is legitimate, remove the old entry with "
        f"`ssh-keygen -R '{pattern}' -f {store_path}` (and from ~/.ssh/known_hosts if it is "
        "there), then connect again."
    )


__all__ = [
    "DEFAULT_KNOWN_HOSTS_PATH",
    "HostKeyInfo",
    "HostKeyStatus",
    "KnownHostsStore",
    "known_hosts_pattern",
]
