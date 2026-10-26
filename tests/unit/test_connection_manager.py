"""Unit tests for RemoteConnectionManager."""

from unittest.mock import AsyncMock, patch

from servicedeck.backend.remote.connection import RemoteConnectionManager
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.remote.models import HelloMessage


async def test_connection_manager_lifecycle() -> None:
    mgr = RemoteConnectionManager()
    dev1 = RemoteDevice(id="dev1", display_name="Device 1", hostname="dev1.local")
    dev2 = RemoteDevice(id="dev2", display_name="Device 2", hostname="dev2.local")

    assert mgr.list_connected() == []
    assert mgr.is_connected("dev1") is False

    hello1 = HelloMessage(host="dev1", user="root", uid=0)
    hello2 = HelloMessage(host="dev2", user="ubuntu", uid=1000)

    with patch("servicedeck.backend.remote.connection.SSHTransport") as mock_transport_cls:
        # Instance 1
        t1 = mock_transport_cls.return_value
        t1.connect = AsyncMock(return_value=hello1)
        t1.disconnect = AsyncMock()
        t1.is_connected = True
        t1.hello = hello1
        t1.device = dev1

        res1 = await mgr.connect(dev1)
        assert res1 == hello1
        assert mgr.is_connected("dev1") is True
        assert mgr.get_transport("dev1") == t1

        # Instance 2
        mock_transport_cls.return_value = None
        t2 = AsyncMock()
        t2.connect = AsyncMock(return_value=hello2)
        t2.disconnect = AsyncMock()
        t2.is_connected = True
        t2.hello = hello2
        t2.device = dev2
        mock_transport_cls.return_value = t2

        res2 = await mgr.connect(dev2)
        assert res2 == hello2
        assert mgr.is_connected("dev2") is True

        assert set(mgr.list_connected()) == {"dev1", "dev2"}

        # Disconnect single device
        await mgr.disconnect("dev1")
        assert mgr.is_connected("dev1") is False
        assert mgr.list_connected() == ["dev2"]

        # Disconnect all
        await mgr.disconnect_all()
        assert mgr.list_connected() == []
