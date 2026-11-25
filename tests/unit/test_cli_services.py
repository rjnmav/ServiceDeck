"""Unit tests for the CLI service commands (list, status, actions, logs)."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from servicedeck.api_client.exceptions import (
    ServiceAuthenticationRequiredError,
    ServiceDeckConnectionError,
    ServiceNotFoundError,
    ServiceOperationError,
    ServicePermissionDeniedError,
)
from servicedeck.api_client.models.service import (
    Service,
    ServiceLogs,
    ServiceOperationResult,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.cli import main


def svc(name: str, active: str = "active", sub: str = "running", desc: str = "") -> Service:
    return Service(
        name=name,
        description=desc,
        load_state="loaded",
        active_state=active,
        sub_state=sub,
        unit_file_state="enabled",
        scope="user",
    )


SERVICES = [
    svc("nginx.service", desc="Web server"),
    svc("broken.service", "failed", "failed"),
    svc("idle.service", "inactive", "dead"),
]


@pytest.fixture
def client() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.list_services.return_value = SERVICES
    with patch("servicedeck.api_client.ServiceDeckClient", return_value=mock) as factory:
        mock.factory = factory
        yield mock


def test_list_prints_table(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "--host", "srv1", "--system"]) == 0
    client.list_services.assert_called_once_with(scope="system", device_id="srv1")
    out = capsys.readouterr().out
    assert "UNIT" in out
    assert "nginx.service" in out
    assert "Web server" in out
    assert "3 service(s)" in out
    client.close.assert_called_once()


def test_list_filters_failed_and_pattern_as_json(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list", "--failed", "--json"]) == 0
    assert [s["name"] for s in json.loads(capsys.readouterr().out)] == ["broken.service"]

    assert main(["list", "ngin*", "--json"]) == 0
    assert [s["name"] for s in json.loads(capsys.readouterr().out)] == ["nginx.service"]


def test_list_uses_url_option_and_env(client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICEDECK_BACKEND_URL", "http://127.0.0.1:9999")
    main(["list"])
    client.factory.assert_called_with(base_url="http://127.0.0.1:9999")
    main(["list", "--url", "http://127.0.0.1:1234"])
    client.factory.assert_called_with(base_url="http://127.0.0.1:1234")


def test_status_active_shows_details_and_logs(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    client.get_service.return_value = svc("nginx.service", desc="Web server")
    client.get_unit_file.return_value = ServiceUnitFile(
        service="nginx.service", fragment_path="/usr/lib/systemd/system/nginx.service", content=""
    )
    client.get_resources.return_value = ServiceResources(
        service="nginx.service", main_pid=42, tasks_current=3, memory_current_bytes=2 * 1024 * 1024
    )
    client.get_logs.return_value = ServiceLogs(service="nginx.service", logs="hello\n")

    assert main(["status", "nginx", "-n", "1"]) == 0
    out = capsys.readouterr().out
    assert "nginx.service - Web server" in out
    assert "/usr/lib/systemd/system/nginx.service" in out
    assert "Main PID: 42" in out
    assert "Memory: 2.0M" in out
    assert out.rstrip().endswith("hello")
    client.get_logs.assert_called_once_with("nginx.service", lines=1, scope="user", device_id=None)


def test_status_exit_codes(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    client.get_service.return_value = svc("idle.service", "inactive", "dead")
    assert main(["status", "idle", "-n", "0", "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["service"]["active_state"] == "inactive"

    client.get_service.side_effect = ServiceNotFoundError(404, "Service unit 'x' not found.")
    assert main(["status", "x"]) == 4
    assert "not found" in capsys.readouterr().err


def test_actions_run_for_each_name_and_report_failures(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    def restart(name: str, **_kwargs: Any) -> ServiceOperationResult:
        if name == "bad":
            raise ServiceOperationError(400, "Unit failed")
        return ServiceOperationResult(success=True, service=name, operation="restart")

    client.restart_service.side_effect = restart

    assert main(["restart", "nginx", "bad", "--host", "srv1"]) == 1
    captured = capsys.readouterr()
    assert "nginx: restarted" in captured.out
    assert "error: bad: Unit failed" in captured.err
    client.restart_service.assert_any_call("nginx", scope="user", device_id="srv1")


def test_remote_action_gets_admin_access_then_retries(
    client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    needs_root = ServicePermissionDeniedError(
        403, "needs admin", error_type="RemoteElevationRequiredError"
    )
    ok = ServiceOperationResult(success=True, service="nginx", operation="start")
    client.start_service.side_effect = [needs_root, ok]

    with (
        patch("servicedeck.cli_services.sys.stdin") as stdin,
        patch("servicedeck.cli_services.getpass.getpass", return_value="pw") as ask,
    ):
        stdin.isatty.return_value = True
        client.elevate_device.side_effect = [
            ServiceAuthenticationRequiredError(401, "needs password", "RemoteSudoAuthError"),
            True,
        ]
        assert main(["start", "nginx", "--host", "srv1", "--system"]) == 0

    assert client.elevate_device.call_args_list[0].kwargs == {"password": None}
    assert client.elevate_device.call_args_list[1].kwargs == {"password": "pw"}
    ask.assert_called_once()
    assert client.start_service.call_count == 2
    assert "nginx: started" in capsys.readouterr().out


def test_logs_prints_journal(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    client.get_logs.return_value = ServiceLogs(service="a.service", logs="one\ntwo")
    assert main(["logs", "a", "-n", "2"]) == 0
    assert capsys.readouterr().out == "one\ntwo\n"


def test_logs_follow_streams_lines(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    stream = MagicMock()
    stream.__iter__.return_value = iter(["one", "two"])
    client.follow_logs.return_value = stream

    assert main(["logs", "a", "-f", "-n", "5", "--host", "srv1"]) == 0
    client.follow_logs.assert_called_once_with("a", lines=5, scope="user", device_id="srv1")
    assert capsys.readouterr().out == "one\ntwo\n"
    stream.close.assert_called_once()


def test_backend_down_gives_hint(client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    client.list_services.side_effect = ServiceDeckConnectionError("connection refused")
    assert main(["list"]) == 1
    assert "servicedeck backend" in capsys.readouterr().err


def test_unknown_option_is_rejected(client: MagicMock) -> None:
    with pytest.raises(SystemExit):
        main(["list", "--bogus"])
