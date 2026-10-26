"""Integration test spawning servicedeck-remote as a real subprocess over stdio pipes."""

import asyncio
import os
import sys

import pytest

from servicedeck.remote.models import (
    GoodbyeMessage,
    HelloMessage,
    RequestMessage,
    ResponseMessage,
)
from servicedeck.remote.protocol import read_message, write_message


@pytest.mark.asyncio
async def test_servicedeck_remote_agent_subprocess() -> None:
    """Spawn servicedeck-remote subprocess, perform handshake, execute requests, and shut down."""
    env = os.environ.copy()
    python_exe = sys.executable

    process = await asyncio.create_subprocess_exec(
        python_exe,
        "-m",
        "servicedeck.remote_agent",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    assert process.stdout is not None
    assert process.stdin is not None

    try:
        # 1. Verify Hello handshake
        hello = await asyncio.wait_for(read_message(process.stdout), timeout=5.0)
        assert isinstance(hello, HelloMessage)
        assert hello.type == "hello"
        assert hello.uid == os.getuid()
        assert hello.servicedeck_version == "2.0.0"

        # 2. Send health.check request
        req1 = RequestMessage(id=1, method="health.check")
        await write_message(process.stdin, req1)

        resp1 = await asyncio.wait_for(read_message(process.stdout), timeout=5.0)
        assert isinstance(resp1, ResponseMessage)
        assert resp1.id == 1
        assert resp1.success is True
        assert resp1.result == {"healthy": True}

        # 3. Send service.list request (user scope)
        req2 = RequestMessage(id=2, method="service.list", params={"scope": "user"})
        await write_message(process.stdin, req2)

        resp2 = await asyncio.wait_for(read_message(process.stdout), timeout=5.0)
        assert isinstance(resp2, ResponseMessage)
        assert resp2.id == 2
        assert resp2.success is True
        assert isinstance(resp2.result, list)

        # 4. Graceful Goodbye shutdown
        goodbye = GoodbyeMessage(reason="test_done")
        await write_message(process.stdin, goodbye)
        process.stdin.close()
        await process.stdin.wait_closed()

        # 5. Process should terminate with exit code 0
        return_code = await asyncio.wait_for(process.wait(), timeout=5.0)
        assert return_code == 0

    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
