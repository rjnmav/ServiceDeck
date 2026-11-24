"""Interactive first-connection onboarding for remote devices.

When connecting fails because the host key is not trusted yet, or because SSH key login
is not set up, this walks the user through the fix instead of just showing an error:

* unknown host key  -> show the fingerprint and ask to trust it;
* key login refused -> ask for the account password once and install the SSH key;
* changed host key  -> explain the risk; there is deliberately no override.

After each step the original operation is retried.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QWidget

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.exceptions import ServiceDeckHTTPError
from servicedeck.api_client.models.remote import HostKeyInfo, KeySetupInfo
from servicedeck.gui.workers.service_worker import run_async_task

HOST_KEY_UNKNOWN = "RemoteHostKeyUnknownError"
HOST_KEY_CHANGED = "RemoteHostKeyChangedError"
AUTH_FAILED = "SSHAuthenticationError"
ELEVATION_REQUIRED = "RemoteElevationRequiredError"
SUDO_AUTH_FAILED = "RemoteSudoAuthError"
SUDO_UNAVAILABLE = "RemoteSudoUnavailableError"

MAX_PASSWORD_ATTEMPTS = 3
# Upper bound on trust/setup/retry rounds for one operation, so a misbehaving server
# can never trap the user in an endless prompt loop.
MAX_ONBOARDING_STEPS = 6


def _error_type(exc: Any) -> str | None:
    return exc.error_type if isinstance(exc, ServiceDeckHTTPError) else None


def needs_onboarding(exc: Any) -> bool:
    """True if ``exc`` is a connection failure the onboarding flow can resolve."""
    return _error_type(exc) in {HOST_KEY_UNKNOWN, HOST_KEY_CHANGED, AUTH_FAILED}


# --- Prompts (module-level so tests can replace them) ---


def confirm_host_key(parent: QWidget | None, info: HostKeyInfo) -> bool:
    """Ask the user to verify and trust a host key fingerprint."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Verify Remote Host")
    box.setText(f"First connection to <b>{info.hostname}</b>. Is this the right machine?")
    box.setInformativeText(
        f"{info.key_type} key fingerprint:<br><code>{info.fingerprint}</code><br><br>"
        "To check, run this on the remote machine and compare:<br>"
        "<code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code><br><br>"
        "Only trust it if the fingerprints match."
    )
    trust = box.addButton("Trust and Connect", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is trust


def ask_password(parent: QWidget | None, target: str, retry_message: str | None) -> str | None:
    """Ask for the remote account password; ``None`` if the user cancels."""
    label = (
        f"Set up passwordless login for <b>{target}</b>.<br><br>"
        "Enter the account password on that machine. ServiceDeck uses it once to install "
        "its SSH key and does <b>not</b> save it."
    )
    if retry_message:
        label = f"<span style='color:#e03131'>{retry_message}</span><br><br>{label}"
    password, ok = QInputDialog.getText(
        parent, "Set Up SSH Key Login", label, QLineEdit.EchoMode.Password
    )
    return password if ok and password else None


def show_changed_host_key(parent: QWidget | None, message: str) -> None:
    QMessageBox.critical(parent, "Remote Host Key Changed", message)


def ask_sudo_password(parent: QWidget | None, target: str, retry_message: str | None) -> str | None:
    """Ask for the remote sudo password; ``None`` if the user cancels."""
    label = (
        f"Managing system services on <b>{target}</b> needs administrator access.<br><br>"
        "Enter your sudo password for that machine. It is used once to start an "
        "administrator session that lasts until you disconnect, and is <b>not</b> saved."
    )
    if retry_message:
        label = f"<span style='color:#e03131'>{retry_message}</span><br><br>{label}"
    password, ok = QInputDialog.getText(
        parent, "Administrator Access", label, QLineEdit.EchoMode.Password
    )
    return password if ok and password else None


def show_sudo_unavailable(parent: QWidget | None, message: str) -> None:
    QMessageBox.warning(
        parent,
        "Administrator Access Unavailable",
        f"{message}<br><br>The remote account must be allowed to use <code>sudo</code> "
        "(for example, be in the <code>wheel</code> or <code>sudo</code> group).",
    )


# --- Flow ---


def handle_onboarding_error(
    parent: QWidget | None,
    client: ServiceDeckClient,
    device_id: str,
    exc: Any,
    *,
    target: str,
    retry: Callable[[], None],
    on_give_up: Callable[[str], None],
    on_key_installed: Callable[[KeySetupInfo], None] | None = None,
    _password_attempt: int = 1,
) -> bool:
    """Resolve an onboarding-related connection error interactively, then ``retry()``.

    Returns False (and does nothing) if ``exc`` is not an onboarding error, so callers
    can fall back to their normal error handling.
    """
    kind = _error_type(exc)

    if kind == HOST_KEY_CHANGED:
        show_changed_host_key(parent, exc.message)
        on_give_up(exc.message)
        return True

    if kind == HOST_KEY_UNKNOWN:
        info = HostKeyInfo.from_dict(exc.details or {})
        if not info.fingerprint or not confirm_host_key(parent, info):
            on_give_up("The remote host key was not trusted.")
            return True
        run_async_task(
            client.trust_host_key,
            device_id,
            info.fingerprint,
            on_success=lambda _info: retry(),
            on_error=lambda msg, _exc: on_give_up(msg),
        )
        return True

    if kind == AUTH_FAILED:
        retry_message = "The password was not accepted." if _password_attempt > 1 else None
        password = ask_password(parent, target, retry_message)
        if password is None:
            on_give_up("SSH key setup was cancelled.")
            return True

        def on_setup_success(result: KeySetupInfo) -> None:
            if on_key_installed is not None:
                on_key_installed(result)
            retry()

        def on_setup_error(msg: str, setup_exc: Any) -> None:
            if _error_type(setup_exc) == AUTH_FAILED and _password_attempt < MAX_PASSWORD_ATTEMPTS:
                handle_onboarding_error(
                    parent,
                    client,
                    device_id,
                    setup_exc,
                    target=target,
                    retry=retry,
                    on_give_up=on_give_up,
                    on_key_installed=on_key_installed,
                    _password_attempt=_password_attempt + 1,
                )
                return
            if needs_onboarding(setup_exc) and _error_type(setup_exc) != AUTH_FAILED:
                handle_onboarding_error(
                    parent,
                    client,
                    device_id,
                    setup_exc,
                    target=target,
                    retry=retry,
                    on_give_up=on_give_up,
                    on_key_installed=on_key_installed,
                )
                return
            on_give_up(msg)

        run_async_task(
            client.setup_key,
            device_id,
            password,
            on_success=on_setup_success,
            on_error=on_setup_error,
        )
        return True

    return False


def needs_elevation(exc: Any) -> bool:
    """True if ``exc`` means a system-scope action needs administrator access."""
    return _error_type(exc) == ELEVATION_REQUIRED


def handle_elevation_error(
    parent: QWidget | None,
    client: ServiceDeckClient,
    device_id: str,
    exc: Any,
    *,
    target: str,
    retry: Callable[[], None],
    on_give_up: Callable[[str], None],
    on_elevated: Callable[[], None] | None = None,
) -> bool:
    """Get administrator access for ``device_id`` interactively, then ``retry()``.

    Passwordless sudo is tried first, so ``NOPASSWD`` setups never see a prompt. Returns
    False (and does nothing) if ``exc`` is not an elevation request.
    """
    if not needs_elevation(exc):
        return False

    def elevate(password: str | None, attempt: int) -> None:
        def succeeded(_elevated: Any) -> None:
            if on_elevated is not None:
                on_elevated()
            retry()

        def failed(msg: str, elevate_exc: Any) -> None:
            kind = _error_type(elevate_exc)
            if kind == SUDO_UNAVAILABLE:
                show_sudo_unavailable(parent, elevate_exc.message)
                on_give_up(elevate_exc.message)
                return
            if kind == SUDO_AUTH_FAILED and attempt < MAX_PASSWORD_ATTEMPTS:
                retry_message = None if password is None else "The password was not accepted."
                new_password = ask_sudo_password(parent, target, retry_message)
                if new_password is None:
                    on_give_up("Administrator access was cancelled.")
                    return
                elevate(new_password, attempt + 1)
                return
            on_give_up(msg)

        run_async_task(
            client.elevate_device, device_id, password, on_success=succeeded, on_error=failed
        )

    elevate(None, 0)
    return True


def connect_with_onboarding(
    parent: QWidget | None,
    client: ServiceDeckClient,
    device_id: str,
    *,
    target: str,
    on_success: Callable[[Any], None],
    on_error: Callable[[str, Any], None],
    on_key_installed: Callable[[KeySetupInfo], None] | None = None,
) -> None:
    """``client.connect_device(device_id)``, resolving host-key and key-login issues."""
    steps = 0
    last_exc: list[Any] = [None]

    def attempt() -> None:
        nonlocal steps
        steps += 1
        run_async_task(client.connect_device, device_id, on_success=on_success, on_error=failed)

    def failed(msg: str, exc: Any) -> None:
        last_exc[0] = exc
        if steps >= MAX_ONBOARDING_STEPS or not handle_onboarding_error(
            parent,
            client,
            device_id,
            exc,
            target=target,
            retry=attempt,
            on_give_up=lambda reason: on_error(reason, last_exc[0]),
            on_key_installed=on_key_installed,
        ):
            on_error(msg, exc)

    attempt()


__all__ = [
    "connect_with_onboarding",
    "handle_elevation_error",
    "handle_onboarding_error",
    "needs_elevation",
    "needs_onboarding",
]
