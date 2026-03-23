"""Tests for service lifecycle: spawn_service and shutdown_service."""

from __future__ import annotations

import sys

import pytest
from pydantic import BaseModel

from amplifier_ipc.host.lifecycle import ServiceProcess, shutdown_service, spawn_service


class TestServiceProcessModel:
    def test_service_process_is_pydantic_base_model(self) -> None:
        """ServiceProcess must be a Pydantic BaseModel, not a dataclass."""
        assert issubclass(ServiceProcess, BaseModel), (
            "ServiceProcess should inherit from pydantic.BaseModel"
        )

    def test_service_process_has_arbitrary_types_allowed(self) -> None:
        """model_config must set arbitrary_types_allowed=True for asyncio/Client fields."""
        config = ServiceProcess.model_config
        assert config.get("arbitrary_types_allowed") is True, (
            "ServiceProcess.model_config must have arbitrary_types_allowed=True"
        )


class TestSpawnService:
    async def test_spawn_service_creates_process(self) -> None:
        """Spawns a process and verifies ServiceProcess fields are populated."""
        service = await spawn_service(
            name="test-svc",
            command=[sys.executable, "-c", "import sys; sys.stdin.read()"],
        )
        try:
            assert isinstance(service, ServiceProcess)
            assert service.name == "test-svc"
            # Process should be running (returncode is None while running)
            assert service.process.returncode is None
            # Client should be attached
            assert service.client is not None
        finally:
            # Clean up the process
            await shutdown_service(service, timeout=2.0)

    async def test_spawn_service_bad_command(self) -> None:
        """Raises FileNotFoundError or OSError for nonexistent commands."""
        with pytest.raises((FileNotFoundError, OSError)):
            await spawn_service(
                name="bad-svc",
                command=["/nonexistent/command/xyz123"],
            )


class TestShutdownService:
    async def test_shutdown_service_graceful(self) -> None:
        """Shutdown with SIGTERM, process exits within timeout."""
        service = await spawn_service(
            name="graceful-svc",
            command=[sys.executable, "-c", "import sys; sys.stdin.read()"],
        )
        # Process should be running
        assert service.process.returncode is None

        await shutdown_service(service, timeout=2.0)

        # After shutdown, process should have exited
        assert service.process.returncode is not None

    async def test_shutdown_service_force_kill(self) -> None:
        """Force-kills a process that ignores SIGTERM."""
        # This process traps SIGTERM and sleeps for a long time
        code = (
            "import signal, time; "
            "signal.signal(signal.SIGTERM, lambda *a: None); "
            "time.sleep(60)"
        )
        service = await spawn_service(
            name="stubborn-svc",
            command=[sys.executable, "-c", code],
        )
        assert service.process.returncode is None

        # Short timeout — SIGTERM will be ignored, should force-kill
        await shutdown_service(service, timeout=0.5)

        # Process should have been killed
        assert service.process.returncode is not None
