"""CLI unit file commands: cat, edit (drop-ins), revert, create, and local sudo elevation."""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from servicedeck.api_client.exceptions import (
    ServiceAuthenticationRequiredError,
    ServicePermissionDeniedError,
)
from servicedeck.api_client.models.service import (
    CreatedService,
    DropInFile,
    OverrideResult,
    RevertResult,
    ServiceUnitFile,
)
from servicedeck.cli import main

OVERRIDE = "/etc/systemd/system/nginx.service.d/override.conf"

UNIT = ServiceUnitFile(
    service="nginx.service",
    fragment_path="/usr/lib/systemd/system/nginx.service",
    content="[Unit]\nDescription=nginx\n\n[Service]\nExecStart=/usr/bin/nginx\n",
    scope="system",
    drop_ins=(
        DropInFile("/usr/lib/systemd/system/nginx.service.d/10-vendor.conf", "[Service]\nA=1\n"),
        DropInFile(OVERRIDE, "[Service]\nNice=5\n", editable=True),
    ),
    override_path=OVERRIDE,
)


def _local_elevation_required() -> ServicePermissionDeniedError:
    return ServicePermissionDeniedError(
        403,
        "Administrator access on this computer is required.",
        "LocalElevationRequiredError",
        {"device_id": None},
    )


@pytest.fixture
def client() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.get_unit_file.return_value = UNIT
    mock.write_override.return_value = OverrideResult(
        service="nginx.service", scope="system", path=OVERRIDE, load_state="loaded"
    )
    with patch("servicedeck.api_client.ServiceDeckClient", return_value=mock):
        yield mock


def test_cat_prints_fragment_then_drop_ins(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["cat", "nginx", "--system"]) == 0
    out = capsys.readouterr().out
    assert out.index("# /usr/lib/systemd/system/nginx.service\n") < out.index("10-vendor.conf")
    assert out.index("10-vendor.conf") < out.index(f"# {OVERRIDE}")
    assert "Nice=5" in out
    client.get_unit_file.assert_called_once_with("nginx", scope="system", device_id=None)


def test_cat_json(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["cat", "nginx", "--json", "--host", "srv1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["drop_ins"][1]["editable"] is True


def test_edit_from_stdin(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("servicedeck.cli_services.sys.stdin", io.StringIO("[Service]\nNice=10\n")):
        assert main(["edit", "nginx", "--system", "--stdin"]) == 0
    client.write_override.assert_called_once_with(
        "nginx", "[Service]\nNice=10\n", scope="system", drop_in="override.conf", device_id=None
    )
    assert f"Wrote {OVERRIDE}" in capsys.readouterr().out


def _fake_editor(new_text: str) -> Any:
    seen: dict[str, str] = {}

    def run(cmd: list[str], check: bool = False) -> SimpleNamespace:
        path = Path(cmd[-1])
        seen["initial"] = path.read_text()
        path.write_text(seen["initial"].replace("[Service]\nNice=5\n", new_text))
        return SimpleNamespace(returncode=0)

    run.seen = seen  # type: ignore[attr-defined]
    return run


def test_edit_opens_editor_with_current_override_and_reference(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EDITOR", "myeditor --wait")
    editor = _fake_editor("[Service]\nNice=7\n")
    with (
        patch("servicedeck.cli_services.sys.stdin") as stdin,
        patch("servicedeck.cli_services.subprocess.run", side_effect=editor) as run,
    ):
        stdin.isatty.return_value = True
        assert main(["edit", "nginx", "--system"]) == 0

    assert run.call_args.args[0][:2] == ["myeditor", "--wait"]
    initial = editor.seen["initial"]
    assert f"### Editing {OVERRIDE}" in initial
    assert "### ExecStart=/usr/bin/nginx" in initial  # vendor unit shown for reference
    assert initial.endswith("[Service]\nNice=5\n")
    content = client.write_override.call_args.args[1]
    assert content == "[Service]\nNice=7\n"  # '###' reference lines are dropped


def test_edit_without_changes_writes_nothing(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EDITOR", "ed")
    with (
        patch("servicedeck.cli_services.sys.stdin") as stdin,
        patch(
            "servicedeck.cli_services.subprocess.run",
            side_effect=_fake_editor("[Service]\nNice=5\n"),
        ),
    ):
        stdin.isatty.return_value = True
        assert main(["edit", "nginx", "--system"]) == 0
    client.write_override.assert_not_called()
    assert "No changes." in capsys.readouterr().out


def test_edit_syntax_error_can_be_aborted(
    client: MagicMock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EDITOR", "ed")
    with (
        patch("servicedeck.cli_services.sys.stdin") as stdin,
        patch(
            "servicedeck.cli_services.subprocess.run",
            side_effect=_fake_editor("[Service]\nnot valid\n"),
        ),
        patch("builtins.input", return_value="a"),
    ):
        stdin.isatty.return_value = True
        assert main(["edit", "nginx", "--system"]) == 1
    client.write_override.assert_not_called()
    assert "expected 'Key=Value'" in capsys.readouterr().err


def test_local_system_edit_asks_for_sudo_password_then_drops_access(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    client.write_override.side_effect = [
        _local_elevation_required(),
        client.write_override.return_value,
    ]
    client.elevate_local.side_effect = [
        ServiceAuthenticationRequiredError(401, "needs password", "RemoteSudoAuthError"),
        True,
    ]
    with (
        patch("servicedeck.cli_services.sys.stdin") as stdin,
        patch("servicedeck.cli_services.getpass.getpass", return_value="pw") as ask,
    ):
        stdin.isatty.return_value = True
        stdin.read.return_value = "[Service]\nNice=10\n"
        assert main(["edit", "nginx", "--system", "--stdin"]) == 0

    assert "this computer" in ask.call_args.args[0]
    assert [c.kwargs for c in client.elevate_local.call_args_list] == [
        {"password": None},
        {"password": "pw"},
    ]
    assert client.write_override.call_count == 2
    client.drop_local_elevation.assert_called_once()
    client.elevate_device.assert_not_called()


def test_remote_elevation_is_kept_for_the_device(client: MagicMock) -> None:
    client.write_override.side_effect = [
        ServicePermissionDeniedError(403, "needs root", "RemoteElevationRequiredError"),
        client.write_override.return_value,
    ]
    with patch("servicedeck.cli_services.sys.stdin", io.StringIO("[Service]\nNice=1\n")):
        assert main(["edit", "nginx", "--system", "--stdin", "--host", "srv1"]) == 0
    client.elevate_device.assert_called_once_with("srv1", password=None)
    client.drop_local_elevation.assert_not_called()


def test_revert_lists_files_and_confirms(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    client.revert_overrides.return_value = RevertResult(
        service="nginx.service", scope="system", removed_paths=(OVERRIDE,)
    )
    with (
        patch("servicedeck.cli_services.sys.stdin") as stdin,
        patch("builtins.input", return_value="y"),
    ):
        stdin.isatty.return_value = True
        assert main(["revert", "nginx", "--system"]) == 0
    out = capsys.readouterr().out
    assert f"  {OVERRIDE}" in out  # listed before confirming
    assert "10-vendor.conf" not in out  # vendor drop-ins are never deleted
    assert f"Removed {OVERRIDE}" in out


def test_revert_without_terminal_needs_yes(client: MagicMock) -> None:
    with patch("servicedeck.cli_services.sys.stdin") as stdin:
        stdin.isatty.return_value = False
        assert main(["revert", "nginx", "--system"]) == 1
    client.revert_overrides.assert_not_called()

    client.revert_overrides.return_value = RevertResult("nginx.service", "system", (OVERRIDE,))
    assert main(["revert", "nginx", "--system", "--yes"]) == 0
    client.revert_overrides.assert_called_once()


def test_revert_with_nothing_to_remove(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    client.get_unit_file.return_value = ServiceUnitFile(
        service="ssh.service", fragment_path="/x", content="", scope="system"
    )
    assert main(["revert", "ssh", "--system", "-y"]) == 0
    assert "no overrides" in capsys.readouterr().out
    client.revert_overrides.assert_not_called()


def test_create_from_file(
    client: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unit = tmp_path / "demo.service"
    unit.write_text("[Unit]\nDescription=demo\n[Service]\nExecStart=/bin/true\n")
    client.create_service.return_value = CreatedService(
        success=True, service="demo.service", path="/etc/systemd/system/demo.service"
    )
    assert main(["create", "demo", "-f", str(unit), "--system", "--overwrite"]) == 0
    client.create_service.assert_called_once_with(
        "demo", unit.read_text(), scope="system", overwrite=True, device_id=None
    )
    assert "Created /etc/systemd/system/demo.service" in capsys.readouterr().out


def test_create_missing_file(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["create", "demo", "-f", "/nonexistent/unit"]) == 1
    assert "cannot read" in capsys.readouterr().err
    client.create_service.assert_not_called()
