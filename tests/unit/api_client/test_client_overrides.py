"""Client support for drop-in overrides and local administrator access."""

import json

import httpx
import pytest

from servicedeck.api_client import (
    AsyncServiceDeckClient,
    InvalidServiceNameError,
    ServiceDeckClient,
    ServicePermissionDeniedError,
    ServiceUnitFile,
)
from servicedeck.api_client.transport import AsyncTransport, SyncTransport

UNIT_JSON = {
    "service": "nginx.service",
    "fragment_path": "/usr/lib/systemd/system/nginx.service",
    "content": "[Unit]\nDescription=nginx\n",
    "scope": "system",
    "drop_ins": [
        {"path": "/usr/lib/systemd/system/nginx.service.d/10-v.conf", "content": "[Service]\n"},
        {
            "path": "/etc/systemd/system/nginx.service.d/override.conf",
            "content": "[Service]\nNice=5\n",
            "editable": True,
        },
    ],
    "override_path": "/etc/systemd/system/nginx.service.d/override.conf",
    "need_daemon_reload": True,
}


def _sync(handler) -> ServiceDeckClient:
    transport = SyncTransport(base_url="http://testserver")
    transport._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://testserver"
    )
    return ServiceDeckClient(transport=transport)


def _async(handler) -> AsyncServiceDeckClient:
    transport = AsyncTransport(base_url="http://testserver")
    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://testserver"
    )
    return AsyncServiceDeckClient(transport=transport)


def test_unit_file_model_with_drop_ins() -> None:
    unit = ServiceUnitFile.from_dict(UNIT_JSON)
    assert [d.editable for d in unit.drop_ins] == [False, True]
    assert unit.editable_drop_ins[0].name == "override.conf"
    assert unit.override_content == "[Service]\nNice=5\n"
    assert unit.need_daemon_reload is True
    text = unit.effective_text()
    assert text.index("# /usr/lib/systemd/system/nginx.service") < text.index(
        "# /etc/systemd/system/nginx.service.d/override.conf"
    )


def test_unit_file_model_is_backward_compatible() -> None:
    unit = ServiceUnitFile.from_dict({"service": "a.service", "fragment_path": None, "content": ""})
    assert unit.drop_ins == ()
    assert unit.override_content is None


def test_write_override_and_revert_remote() -> None:
    seen: list[tuple[str, str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, request.url.query.decode(), body))
        if request.method == "PUT":
            return httpx.Response(
                200,
                json={
                    "service": "nginx.service",
                    "scope": "system",
                    "path": "/etc/systemd/system/nginx.service.d/override.conf",
                    "load_state": "loaded",
                    "warnings": ["Line 1: unknown section [X] (systemd will ignore it)."],
                },
            )
        return httpx.Response(
            200,
            json={
                "service": "nginx.service",
                "scope": "system",
                "removed_paths": ["/etc/systemd/system/nginx.service.d/override.conf"],
            },
        )

    client = _sync(handler)
    result = client.write_override("nginx", "[Service]\nNice=5\n", scope="system", device_id="s1")
    assert result.load_state == "loaded"
    assert len(result.warnings) == 1
    reverted = client.revert_overrides("nginx", scope="system", device_id="s1")
    assert reverted.removed_paths == ("/etc/systemd/system/nginx.service.d/override.conf",)

    assert seen[0][:3] == ("PUT", "/api/remote/s1/services/nginx/override", "scope=system")
    assert seen[0][3] == {"content": "[Service]\nNice=5\n", "drop_in": "override.conf"}
    assert seen[1][:2] == ("DELETE", "/api/remote/s1/services/nginx/override")


def test_local_elevation_calls() -> None:
    calls: list[tuple[str, dict]] = []
    state = {"elevated": False}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/elevation"
        body = json.loads(request.content) if request.content else {}
        calls.append((request.method, body))
        if request.method == "POST":
            state["elevated"] = True
        elif request.method == "DELETE":
            state["elevated"] = False
        return httpx.Response(200, json={**state, "idle_timeout": 900})

    client = _sync(handler)
    assert client.get_local_elevation() is False
    assert client.elevate_local("pw") is True
    assert client.elevate_local() is True
    client.drop_local_elevation()
    assert [c[0] for c in calls] == ["GET", "POST", "POST", "DELETE"]
    assert calls[1][1] == {"password": "pw"}
    assert calls[2][1] == {}


def test_local_elevation_required_keeps_error_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": "LocalElevationRequiredError",
                "message": "Administrator access on this computer is required.",
                "details": {"device_id": None, "scope": "system"},
            },
        )

    with pytest.raises(ServicePermissionDeniedError) as info:
        _sync(handler).write_override("ssh", "[Service]\n", scope="system")
    assert info.value.error_type == "LocalElevationRequiredError"


def test_invalid_service_name_maps_to_its_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "InvalidServiceNameError", "message": "bad", "details": {}}
        )

    with pytest.raises(InvalidServiceNameError):
        _sync(handler).get_unit_file("bad name")


async def test_async_override_and_elevation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/services/ssh/unit-file":
            return httpx.Response(200, json=UNIT_JSON)
        if path == "/api/services/ssh/override" and request.method == "PUT":
            return httpx.Response(
                200, json={"service": "ssh.service", "scope": "system", "path": "/x"}
            )
        if path == "/api/services/ssh/override":
            return httpx.Response(200, json={"service": "ssh.service", "scope": "system"})
        if path == "/api/elevation":
            return httpx.Response(200, json={"elevated": request.method == "POST"})
        return httpx.Response(404, json={"error": "NotFound", "message": path})

    client = _async(handler)
    try:
        unit = await client.get_unit_file("ssh", scope="system")
        assert unit.override_content == "[Service]\nNice=5\n"
        assert (await client.write_override("ssh", "[Service]\n", scope="system")).path == "/x"
        assert (await client.revert_overrides("ssh", scope="system")).removed_paths == ()
        assert await client.elevate_local("pw") is True
        assert await client.get_local_elevation() is False
        await client.drop_local_elevation()
    finally:
        await client.close()
