"""Service lifecycle: spawn and gracefully shut down subprocess services."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from amplifier_ipc.protocol.client import Client

logger = logging.getLogger(__name__)


@dataclass
class ServiceProcess:
    """A running service subprocess with an attached JSON-RPC client."""

    name: str
    process: asyncio.subprocess.Process
    client: Client


async def spawn_service(
    name: str,
    command: list[str],
    working_dir: str | None = None,
) -> ServiceProcess:
    """Spawn a subprocess service and attach a JSON-RPC client to it.

    Args:
        name: Logical name for the service.
        command: Command and arguments to execute.
        working_dir: Optional working directory for the subprocess.

    Returns:
        A ServiceProcess with the running process and attached Client.

    Raises:
        FileNotFoundError: If the command executable is not found.
        OSError: If the subprocess cannot be created.
    """
    # Use a large stream limit so that messages containing large payloads
    # (e.g. orchestrator.execute with a full system prompt, or large describe
    # responses) are not truncated by the default 64 KB asyncio limit.
    _STREAM_LIMIT = 10 * 1024 * 1024  # 10 MB

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
        limit=_STREAM_LIMIT,
    )

    assert process.stdout is not None
    assert process.stdin is not None

    client = Client(reader=process.stdout, writer=process.stdin)
    return ServiceProcess(name=name, process=process, client=client)


async def shutdown_service(service: ServiceProcess, timeout: float = 5.0) -> None:
    """Gracefully shut down a service subprocess.

    Sends SIGTERM and waits up to *timeout* seconds for the process to exit.
    If the process has not exited by then, logs a warning and sends SIGKILL.

    Args:
        service: The ServiceProcess to shut down.
        timeout: Seconds to wait for graceful exit before force-killing.
    """
    process = service.process

    # Already exited — nothing to do
    if process.returncode is not None:
        return

    # Close stdin to signal EOF to the child
    if process.stdin is not None:
        process.stdin.close()

    # Send SIGTERM
    try:
        process.terminate()
    except ProcessLookupError:
        return

    # Wait up to timeout for the process to exit
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "Service %r did not exit within %.1fs after SIGTERM; sending SIGKILL",
            service.name,
            timeout,
        )
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
