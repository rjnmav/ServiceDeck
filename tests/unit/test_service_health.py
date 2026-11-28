"""Service health: restart count, last exit and failure time (API, client model, CLI)."""

import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from tests.conftest import FakeSystemdAdapter

from servicedeck.api_client.models.service import (
    Service,
    ServiceResources,
    describe_exit,
    format_ago,
)
from servicedeck.cli import main

# --- Client model helpers ---


@pytest.mark.parametrize(
    ("code", "status", "text"),
    [
        (1, 0, "exited, status=0/SUCCESS"),
        (1, 1, "exited, status=1/FAILURE"),
        (1, 203, "exited, status=203/EXEC"),
        (1, 42, "exited, status=42"),
        (2, 9, "killed, signal=KILL"),
        (3, 11, "dumped, signal=SEGV"),
        (2, 999, "killed, signal=999"),
        (0, 0, None),
        (None, None, None),
    ],
)
def test_describe_exit(code: int | None, status: int | None, text: str | None) -> None:
    assert describe_exit(code, status) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0s"),
        (42, "42s"),
        (300, "5m"),
        (3600, "1h"),
        (3 * 3600 + 720, "3h 12m"),
        (86400 * 2 + 3600 * 4, "2d 4h"),
    ],
)
def test_format_ago(seconds: float, text: str) -> None:
    assert format_ago(seconds) == text


def test_failed_for_seconds() -> None:
    failed_at = time.time() - 125
    res = ServiceResources.from_dict(
        {
            "service": "web.service",
            "active_state": "failed",
            "state_change_timestamp": int(failed_at * 1_000_000),
            "n_restarts": 4,
            "result": "exit-code",
            "exec_main_code": 1,
            "exec_main_status": 1,
        }
    )
    assert res.is_failed
    assert 124 <= (res.failed_for_seconds() or 0) <= 127
    assert res.last_exit == "exited, status=1/FAILURE"
    assert res.n_restarts == 4

    active = ServiceResources.from_dict({"service": "web.service", "active_state": "active"})
    assert active.failed_for_seconds() is None
    assert active.n_restarts is None  # older backend: field absent


# --- API ---


async def test_resources_endpoint_reports_health(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.restart_counts[("user", "pipewire.service")] = 3
    data = (await client.get("/api/services/pipewire/resources")).json()
    assert data["n_restarts"] == 3
    assert data["active_state"] == "active"
    assert data["result"] == "success"
    assert data["state_change_timestamp"] == 1710000000000000


async def test_resources_endpoint_reports_real_failed_state(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    failed = next(
        s for (scope, _), s in fake_adapter._services.items() if s.active_state == "failed"
    )
    data = (
        await client.get(f"/api/services/{failed.name}/resources", params={"scope": failed.scope})
    ).json()
    # Previously this was flattened to "inactive".
    assert data["active_state"] == "failed"
    assert data["result"] == "exit-code"
    assert (data["exec_main_code"], data["exec_main_status"]) == (1, 1)


# --- CLI ---


@pytest.fixture
def cli_client() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.get_unit_file.side_effect = Exception("not needed")
    with patch("servicedeck.api_client.ServiceDeckClient", return_value=mock):
        yield mock


def _svc(active: str, sub: str) -> Service:
    return Service(
        name="web.service",
        description="Web",
        load_state="loaded",
        active_state=active,
        sub_state=sub,
        unit_file_state="enabled",
        scope="user",
    )


def test_status_shows_failure_details(
    cli_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    from servicedeck.api_client.exceptions import ServiceDeckAPIError

    cli_client.get_unit_file.side_effect = ServiceDeckAPIError("no")
    cli_client.get_service.return_value = _svc("failed", "failed")
    cli_client.get_resources.return_value = ServiceResources(
        service="web.service",
        active_state="failed",
        n_restarts=5,
        result="exit-code",
        exec_main_code=1,
        exec_main_status=203,
        state_change_timestamp=int((time.time() - 300) * 1_000_000),
    )
    assert main(["status", "web", "-n", "0"]) == 3
    out = capsys.readouterr().out
    assert "Failed: Result: exit-code; since" in out
    assert "5m ago" in out
    assert "Last exit: exited, status=203/EXEC" in out
    assert "Restarts: 5" in out


def test_status_of_healthy_service_hides_exit(
    cli_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    from servicedeck.api_client.exceptions import ServiceDeckAPIError

    cli_client.get_unit_file.side_effect = ServiceDeckAPIError("no")
    cli_client.get_service.return_value = _svc("active", "running")
    cli_client.get_resources.return_value = ServiceResources(
        service="web.service",
        active_state="active",
        n_restarts=0,
        result="success",
        exec_main_code=0,
        exec_main_status=0,
    )
    assert main(["status", "web", "-n", "0"]) == 0
    out = capsys.readouterr().out
    assert "Restarts: 0" in out
    assert "Last exit" not in out
    assert "Failed:" not in out
