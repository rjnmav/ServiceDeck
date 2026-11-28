"""Drop-in override routes, local system-scope writes and the local administrator session."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import FakeSystemdAdapter

from servicedeck.backend.app.application import create_app
from servicedeck.backend.config.settings import Settings
from servicedeck.backend.core.local_admin import LocalAdminSession
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import RemoteConnectionError, RemoteSudoAuthError
from servicedeck.remote.models import HelloMessage, RequestMessage, ResponseMessage
from servicedeck.remote_agent.dispatcher import RequestDispatcher


class FakeRootAgent:
    """Stands in for LocalPrivilegedAgent: answers requests with a real dispatcher."""

    def __init__(self, adapter: FakeSystemdAdapter, password: str = "secret") -> None:
        self.adapter = adapter
        self.password = password
        self.dispatcher = RequestDispatcher(ServiceManager(adapter=adapter))
        self.alive = False
        self.requests: list[RequestMessage] = []
        self.fail_requests = False

    @property
    def is_alive(self) -> bool:
        return self.alive

    async def start(self, password: str | None, timeout: float = 30.0) -> HelloMessage:
        if password != self.password:
            raise RemoteSudoAuthError(
                "sudo on this computer needs the administrator password.",
                details={"password_required": password is None},
            )
        self.alive = True
        return HelloMessage(host="localhost", user="root", uid=0)

    async def send_request(self, request: RequestMessage, timeout: float = 30.0) -> ResponseMessage:
        if self.fail_requests:
            self.alive = False
            raise RemoteConnectionError("The administrator session on this computer has ended.")
        self.requests.append(request)
        return await self.dispatcher.dispatch(request)

    async def close(self) -> None:
        self.alive = False


@pytest.fixture
def root_adapter() -> FakeSystemdAdapter:
    return FakeSystemdAdapter()


@pytest.fixture
def root_agent(root_adapter: FakeSystemdAdapter) -> FakeRootAgent:
    return FakeRootAgent(root_adapter)


@pytest.fixture
def local_admin(root_agent: FakeRootAgent) -> LocalAdminSession:
    return LocalAdminSession(idle_timeout=0, agent_factory=lambda: root_agent)


@pytest.fixture
async def admin_client(
    service_manager: ServiceManager, test_settings: Settings, local_admin: LocalAdminSession
) -> AsyncIterator[AsyncClient]:
    app: Any = create_app(
        settings=test_settings, service_manager=service_manager, local_admin=local_admin
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# --- Unit file with drop-ins ---


async def test_unit_file_lists_drop_ins(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.vendor_drop_ins[("user", "pipewire.service")] = [
        ("/usr/lib/systemd/user/pipewire.service.d/10-vendor.conf", "[Service]\nNice=1\n")
    ]
    fake_adapter.drop_ins[("user", "pipewire.service")] = {"override.conf": "[Service]\nNice=5\n"}

    response = await client.get("/api/services/pipewire/unit-file")

    assert response.status_code == 200
    data = response.json()
    assert [d["editable"] for d in data["drop_ins"]] == [False, True]
    assert data["drop_ins"][1]["content"] == "[Service]\nNice=5\n"
    assert data["override_path"].endswith("pipewire.service.d/override.conf")
    assert data["need_daemon_reload"] is False


# --- Writing and reverting overrides (user scope, in-process) ---


async def test_write_override_user_scope(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    response = await client.put(
        "/api/services/pipewire/override",
        params={"scope": "user"},
        json={"content": "[Service]\nNice=5\n"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["path"].endswith("pipewire.service.d/override.conf")
    assert data["removed"] is False
    assert data["load_state"] == "loaded"
    assert fake_adapter.drop_ins[("user", "pipewire.service")] == {
        "override.conf": "[Service]\nNice=5\n"
    }


async def test_write_override_reports_syntax_warnings(client: AsyncClient) -> None:
    response = await client.put(
        "/api/services/pipewire/override",
        json={"content": "[Servcie]\nNice=5\n"},
    )
    assert response.status_code == 200
    assert any("unknown section [Servcie]" in w for w in response.json()["warnings"])


async def test_write_override_rejects_syntax_errors(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    response = await client.put("/api/services/pipewire/override", json={"content": "Nice=5\n"})
    assert response.status_code == 400
    assert response.json()["error"] == "ServiceOperationError"
    assert "inside a section" in response.json()["message"]
    assert ("user", "pipewire.service") not in fake_adapter.drop_ins


async def test_write_override_rolled_back_by_systemd(client: AsyncClient) -> None:
    response = await client.put(
        "/api/services/pipewire/override",
        json={"content": "[Service]\nBadSetting=1\n"},
    )
    assert response.status_code == 400
    assert "previous configuration was restored" in response.json()["message"]


async def test_comment_only_override_removes_drop_in(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.drop_ins[("user", "pipewire.service")] = {"override.conf": "[Service]\nNice=5\n"}
    response = await client.put(
        "/api/services/pipewire/override", json={"content": "# nothing here\n"}
    )
    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert fake_adapter.drop_ins[("user", "pipewire.service")] == {}


async def test_revert_overrides(client: AsyncClient, fake_adapter: FakeSystemdAdapter) -> None:
    fake_adapter.drop_ins[("user", "pipewire.service")] = {
        "override.conf": "[Service]\nNice=5\n",
        "limits.conf": "[Service]\nMemoryMax=1G\n",
    }
    response = await client.delete("/api/services/pipewire/override")
    assert response.status_code == 200
    removed = response.json()["removed_paths"]
    assert [p.rsplit("/", 1)[1] for p in removed] == ["limits.conf", "override.conf"]
    assert ("user", "pipewire.service") not in fake_adapter.drop_ins


async def test_override_for_unknown_service_is_404(client: AsyncClient) -> None:
    response = await client.put(
        "/api/services/missing/override", json={"content": "[Service]\nNice=5\n"}
    )
    assert response.status_code == 404


# --- Local system scope: administrator access through the root agent ---


async def test_system_override_without_admin_asks_for_elevation(
    admin_client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.denied_operations.add(("edit", "system"))
    response = await admin_client.put(
        "/api/services/ssh/override",
        params={"scope": "system"},
        json={"content": "[Service]\nNice=5\n"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "LocalElevationRequiredError"
    assert body["details"]["device_id"] is None
    assert body["details"]["scope"] == "system"


async def test_system_create_without_admin_asks_for_elevation(
    admin_client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.denied_operations.add(("create", "system"))
    response = await admin_client.post(
        "/api/services/create",
        json={
            "name": "custom.service",
            "content": "[Unit]\nDescription=x\n[Service]\nExecStart=/bin/true\n",
            "scope": "system",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"] == "LocalElevationRequiredError"


async def test_user_scope_denial_is_not_an_elevation_request(
    admin_client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.denied_operations.add(("edit", "user"))
    response = await admin_client.put(
        "/api/services/pipewire/override", json={"content": "[Service]\nNice=5\n"}
    )
    assert response.status_code == 403
    assert response.json()["error"] == "AuthorizationDenied"


async def test_elevate_then_system_writes_go_to_root_agent(
    admin_client: AsyncClient,
    fake_adapter: FakeSystemdAdapter,
    root_adapter: FakeSystemdAdapter,
    root_agent: FakeRootAgent,
) -> None:
    fake_adapter.denied_operations.update({("edit", "system"), ("create", "system")})

    assert (await admin_client.get("/api/elevation")).json()["elevated"] is False
    response = await admin_client.post("/api/elevation", json={"password": "secret"})
    assert response.status_code == 200
    assert response.json()["elevated"] is True

    response = await admin_client.put(
        "/api/services/ssh/override",
        params={"scope": "system"},
        json={"content": "[Service]\nNice=5\n"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["path"] == "/etc/systemd/system/ssh.service.d/override.conf"
    assert root_adapter.drop_ins[("system", "ssh.service")] == {
        "override.conf": "[Service]\nNice=5\n"
    }
    assert ("system", "ssh.service") not in fake_adapter.drop_ins

    response = await admin_client.post(
        "/api/services/create",
        json={
            "name": "custom.service",
            "content": "[Unit]\nDescription=x\n[Service]\nExecStart=/bin/true\n",
            "scope": "system",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["path"] == "/etc/systemd/system/custom.service"

    response = await admin_client.delete("/api/services/ssh/override", params={"scope": "system"})
    assert response.json()["removed_paths"] == ["/etc/systemd/system/ssh.service.d/override.conf"]
    assert [r.method for r in root_agent.requests] == [
        "service.override.write",
        "service.create",
        "service.override.revert",
    ]
    assert all(r.params["scope"] == "system" for r in root_agent.requests)

    # User-scope writes never use the root agent.
    await admin_client.put(
        "/api/services/pipewire/override", json={"content": "[Service]\nNice=5\n"}
    )
    assert len(root_agent.requests) == 3

    response = await admin_client.delete("/api/elevation")
    assert response.json()["elevated"] is False


async def test_root_agent_errors_keep_their_type(
    admin_client: AsyncClient, root_agent: FakeRootAgent
) -> None:
    await admin_client.post("/api/elevation", json={"password": "secret"})
    response = await admin_client.put(
        "/api/services/missing/override",
        params={"scope": "system"},
        json={"content": "[Service]\nNice=5\n"},
    )
    assert response.status_code == 404


async def test_wrong_password_is_401_and_not_echoed(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/elevation", json={"password": "hunter2"})
    assert response.status_code == 401
    assert response.json()["error"] == "RemoteSudoAuthError"
    assert "hunter2" not in response.text
    assert (await admin_client.get("/api/elevation")).json()["elevated"] is False


async def test_ended_root_agent_asks_for_elevation_again(
    admin_client: AsyncClient, fake_adapter: FakeSystemdAdapter, root_agent: FakeRootAgent
) -> None:
    await admin_client.post("/api/elevation", json={"password": "secret"})
    root_agent.fail_requests = True
    response = await admin_client.put(
        "/api/services/ssh/override",
        params={"scope": "system"},
        json={"content": "[Service]\nNice=5\n"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "LocalElevationRequiredError"
    assert (await admin_client.get("/api/elevation")).json()["elevated"] is False
