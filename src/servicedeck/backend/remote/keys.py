"""SSH login keys used to authenticate to remote hosts.

By default ServiceDeck uses a **dedicated** ed25519 key pair under
``~/.config/servicedeck/ssh/``. It has no passphrase so the backend can connect unattended
(no ssh-agent needed), carries the comment ``servicedeck@<this-host>`` so it is easy to find
and revoke in a remote ``authorized_keys``, and is installed with the OpenSSH ``restrict``
option because the agent needs no forwarding or PTY.

A device can instead name the user's own key via ``ssh_key_path``; that key is installed
as-is (without ``restrict``, which would break the user's normal ``ssh`` use).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from dataclasses import dataclass
from pathlib import Path

import asyncssh

from servicedeck.backend.exceptions import RemoteKeySetupError
from servicedeck.backend.remote.device_config import RemoteDevice

logger = logging.getLogger(__name__)

DEFAULT_KEY_DIR = Path.home() / ".config" / "servicedeck" / "ssh"
DEDICATED_KEY_NAME = "id_ed25519"

_generate_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class LoginKey:
    """A login key pair: where the private key lives and its public half."""

    private_path: Path
    algorithm: str
    blob: str
    comment: str
    fingerprint: str
    dedicated: bool

    def authorized_keys_line(self) -> str:
        """The line to add to a remote ``~/.ssh/authorized_keys``."""
        options = "restrict " if self.dedicated else ""
        return f"{options}{self.algorithm} {self.blob} {self.comment}".rstrip()


def _parse_public_key(text: str, private_path: Path, dedicated: bool) -> LoginKey:
    parts = text.strip().split(None, 2)
    if len(parts) < 2:
        raise RemoteKeySetupError(
            f"Public key for {private_path} is not in OpenSSH format",
            details={"key_path": str(private_path)},
        )
    try:
        fingerprint = asyncssh.import_public_key(" ".join(parts[:2])).get_fingerprint()
    except (asyncssh.KeyImportError, ValueError) as exc:
        raise RemoteKeySetupError(
            f"Public key for {private_path} could not be read: {exc}",
            details={"key_path": str(private_path)},
        ) from exc
    return LoginKey(
        private_path=private_path,
        algorithm=parts[0],
        blob=parts[1],
        comment=parts[2] if len(parts) > 2 else "",
        fingerprint=fingerprint,
        dedicated=dedicated,
    )


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_user_key(private_path: Path) -> LoginKey:
    """Load a user-chosen key, preferring its ``.pub`` file."""
    private_path = private_path.expanduser()
    pub_path = private_path.with_name(private_path.name + ".pub")
    if pub_path.is_file():
        return _parse_public_key(pub_path.read_text(encoding="utf-8"), private_path, False)
    try:
        key = asyncssh.read_private_key(private_path)
    except (asyncssh.KeyImportError, asyncssh.KeyEncryptionError) as exc:
        # asyncssh reports an encrypted key as KeyImportError("Passphrase must be ...").
        if isinstance(exc, asyncssh.KeyEncryptionError) or "assphrase" in str(exc):
            raise RemoteKeySetupError(
                f"{private_path} is passphrase-protected and has no {pub_path.name} next to it. "
                f"Create it with `ssh-keygen -y -f {private_path} > {pub_path}` and try again.",
                details={"key_path": str(private_path)},
            ) from exc
        raise RemoteKeySetupError(
            f"Could not read SSH key {private_path}: {exc}",
            details={"key_path": str(private_path)},
        ) from exc
    except OSError as exc:
        raise RemoteKeySetupError(
            f"Could not read SSH key {private_path}: {exc}",
            details={"key_path": str(private_path)},
        ) from exc
    return _parse_public_key(key.export_public_key().decode("ascii"), private_path, False)


class ServiceDeckKeyStore:
    """Creates and loads the dedicated ServiceDeck login key."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or DEFAULT_KEY_DIR

    @property
    def private_path(self) -> Path:
        return self._dir / DEDICATED_KEY_NAME

    @property
    def public_path(self) -> Path:
        return self._dir / f"{DEDICATED_KEY_NAME}.pub"

    def ensure_key(self) -> LoginKey:
        """Return the dedicated key, generating it on first use."""
        with _generate_lock:
            if not (self.private_path.is_file() and self.public_path.is_file()):
                self._generate()
        return _parse_public_key(
            self.public_path.read_text(encoding="utf-8"), self.private_path, True
        )

    def _generate(self) -> None:
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._dir, 0o700)
        comment = f"servicedeck@{socket.gethostname()}"
        key = asyncssh.generate_private_key("ssh-ed25519", comment=comment)
        _write_atomic(self.private_path, key.export_private_key(), 0o600)
        _write_atomic(self.public_path, key.export_public_key(), 0o644)
        logger.info(
            "Generated ServiceDeck SSH login key %s (%s)",
            self.private_path,
            key.get_fingerprint(),
        )

    def key_for_device(self, device: RemoteDevice) -> LoginKey:
        """The key to install for ``device``: its chosen key, else the dedicated one."""
        if device.ssh_key_path:
            chosen = Path(device.ssh_key_path).expanduser()
            if chosen.resolve() == self.private_path.resolve():
                return self.ensure_key()
            return load_user_key(chosen)
        return self.ensure_key()


__all__ = [
    "DEFAULT_KEY_DIR",
    "LoginKey",
    "ServiceDeckKeyStore",
    "load_user_key",
]
