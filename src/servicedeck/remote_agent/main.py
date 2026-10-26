"""Entry point for the servicedeck-remote headless agent.

Launched via SSH to execute ServiceDeck protocol requests against
the local systemd instance using dbus-fast. Does NOT listen on any
network port.
"""

import argparse
import asyncio
import ctypes
import ctypes.util
import getpass
import logging
import os
import signal
import sys

from servicedeck.backend.config.settings import Settings
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.infrastructure.dbus.connection import DbusConnectionManager
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter
from servicedeck.remote_agent.dispatcher import RequestDispatcher
from servicedeck.remote_agent.server import ProtocolServer

logger = logging.getLogger("servicedeck.remote_agent")


def _setup_pdeathsig() -> None:
    """Set PR_SET_PDEATHSIG to SIGTERM on Linux.

    Ensures the agent terminates immediately if the parent SSH process exits,
    preventing orphaned bridge processes.
    """
    if sys.platform != "linux":
        return

    libc_path = ctypes.util.find_library("c")
    if not libc_path:
        return

    try:
        libc = ctypes.CDLL(libc_path, use_errno=True)
        PR_SET_PDEATHSIG = 1
        res = libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
        if res != 0:
            logger.warning("Failed to set PR_SET_PDEATHSIG (code %d)", res)
    except Exception as exc:
        logger.warning("Could not set PR_SET_PDEATHSIG: %s", exc)


async def _diagnose_identity() -> None:
    """Print the complete Linux, D-Bus, and Polkit identity chain to stderr."""
    sys.stderr.write("=== ServiceDeck Remote Identity Diagnosis ===\n")
    sys.stderr.write(f"1. Unix Process UID: {os.getuid()}\n")
    sys.stderr.write(f"2. Unix Process GID: {os.getgid()}\n")
    sys.stderr.write(f"3. Unix Username: {getpass.getuser()}\n")
    sys.stderr.write(f"4. PID: {os.getpid()}\n")
    sys.stderr.write(
        f"5. DBUS_SESSION_BUS_ADDRESS: {os.environ.get('DBUS_SESSION_BUS_ADDRESS', 'NOT SET')}\n"
    )
    sys.stderr.write(
        f"6. DBUS_SYSTEM_BUS_ADDRESS: {os.environ.get('DBUS_SYSTEM_BUS_ADDRESS', 'NOT SET')}\n"
    )
    sys.stderr.write(f"7. XDG_RUNTIME_DIR: {os.environ.get('XDG_RUNTIME_DIR', 'NOT SET')}\n")

    settings = Settings()
    connection_manager = DbusConnectionManager(settings=settings)
    adapter = DbusSystemdAdapter(connection_manager=connection_manager, settings=settings)
    manager = ServiceManager(adapter=adapter)

    sys.stderr.write("8. Probing system scope D-Bus connectivity...\n")
    try:
        system_healthy = await manager.is_healthy(scope="system")
        sys.stderr.write(f"   -> System scope healthy: {system_healthy}\n")
    except Exception as exc:
        sys.stderr.write(f"   -> System scope connection failed: {exc}\n")

    sys.stderr.write("9. Probing user scope D-Bus connectivity...\n")
    try:
        user_healthy = await manager.is_healthy(scope="user")
        sys.stderr.write(f"   -> User scope healthy: {user_healthy}\n")
    except Exception as exc:
        sys.stderr.write(f"   -> User scope connection failed: {exc}\n")

    await connection_manager.disconnect()
    sys.stderr.write("=============================================\n")


async def async_main(log_level: int) -> int:
    """Asynchronous entry point for the remote execution agent."""
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger.info("Initializing servicedeck-remote agent (PID %d)", os.getpid())

    _setup_pdeathsig()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _sig_handler() -> None:
        logger.info("Termination signal received. Stopping server.")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except (NotImplementedError, RuntimeError):
            pass

    settings = Settings()
    connection_manager = DbusConnectionManager(settings=settings)
    adapter = DbusSystemdAdapter(connection_manager=connection_manager, settings=settings)
    service_manager = ServiceManager(adapter=adapter)

    # Establish async stdin reader
    reader = asyncio.StreamReader()
    read_protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: read_protocol, sys.stdin.buffer)

    # Establish async stdout writer
    write_transport, write_protocol = await loop.connect_write_pipe(
        lambda: asyncio.streams.FlowControlMixin(loop=loop),
        sys.stdout.buffer,
    )
    writer = asyncio.StreamWriter(write_transport, write_protocol, reader, loop)

    dispatcher = RequestDispatcher(service_manager=service_manager)
    server = ProtocolServer(dispatcher=dispatcher, reader=reader, writer=writer)

    try:
        logger.debug("Connecting to systemd D-Bus...")
        await connection_manager.connect()

        server_task = asyncio.create_task(server.run())
        stop_task = asyncio.create_task(stop_event.wait())

        done, _ = await asyncio.wait(
            [server_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if stop_task in done:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
            await server.shutdown()

        return 0
    except Exception as exc:
        logger.exception("Agent runtime fatal error: %s", exc)
        return 1
    finally:
        logger.debug("Disconnecting D-Bus connection manager...")
        await connection_manager.disconnect()


def main(argv: list[str] | None = None) -> int:
    """Synchronous CLI entry point for servicedeck-remote."""
    parser = argparse.ArgumentParser(
        prog="servicedeck-remote",
        description="ServiceDeck 2.0 headless remote systemd management agent.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level directed to stderr (default: INFO)",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print diagnostic system/user UID, D-Bus, and Polkit details to stderr and exit.",
    )

    args = parser.parse_args(argv)
    log_level = getattr(logging, args.log_level)

    if args.diagnose:
        asyncio.run(_diagnose_identity())
        return 0

    return asyncio.run(async_main(log_level))


if __name__ == "__main__":
    sys.exit(main())
