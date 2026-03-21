"""Hook executor for running shell commands.

Executes Claude Code hooks as subprocesses with proper I/O handling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HookExecutor:
    """Execute Claude Code hooks as shell commands."""

    def __init__(self, project_dir: Path, hooks_dir: Path, session_id: str):
        self.project_dir = project_dir
        self.hooks_dir = hooks_dir
        self.session_id = session_id
        self._env_file: Path | None = None
        self._persisted_env: dict[str, str] = {}

    async def execute(
        self, command: str, input_data: dict[str, Any], timeout: float = 30.0
    ) -> tuple[int, str, str]:
        """Execute a hook command.

        Args:
            command: Shell command to execute
            input_data: JSON data to pass on stdin
            timeout: Timeout in seconds

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        env = self._prepare_environment()
        expanded_command = os.path.expandvars(command)

        proc = await asyncio.create_subprocess_shell(
            expanded_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(self.project_dir),
        )

        input_json = json.dumps(input_data).encode("utf-8")

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=input_json), timeout=timeout
            )

            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )

        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (1, "", f"Hook timed out after {timeout}s")

        except Exception as e:
            return (1, "", f"Hook execution failed: {str(e)}")

        finally:
            self._load_persisted_env()

    def _prepare_environment(self) -> dict[str, str]:
        """Prepare environment variables for hook execution."""
        env = os.environ.copy()

        env["AMPLIFIER_PROJECT_DIR"] = str(self.project_dir)
        env["AMPLIFIER_HOOKS_DIR"] = str(self.hooks_dir)
        env["AMPLIFIER_SESSION_ID"] = self.session_id
        env["CLAUDE_PROJECT_DIR"] = str(self.project_dir)
        env["AMPLIFIER_ENV_FILE"] = str(self._get_env_file())
        env["CLAUDE_ENV_FILE"] = env["AMPLIFIER_ENV_FILE"]

        env.update(self._persisted_env)

        return env

    def _get_env_file(self) -> Path:
        """Get or create the environment persistence file."""
        if self._env_file is None:
            fd, path = tempfile.mkstemp(
                prefix=f"amplifier-env-{self.session_id[:8]}-",
                suffix=".env",
            )
            os.close(fd)
            self._env_file = Path(path)
        return self._env_file

    def _load_persisted_env(self) -> None:
        """Load environment variables persisted by hooks."""
        if self._env_file is None or not self._env_file.exists():
            return

        try:
            content = self._env_file.read_text()
            for line in content.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("export "):
                    line = line[7:]

                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    self._persisted_env[key] = value
        except Exception as e:
            logger.debug("Failed to load persisted env: %s", e)

    def cleanup(self) -> None:
        """Clean up resources (remove temp env file)."""
        if self._env_file is not None and self._env_file.exists():
            try:
                self._env_file.unlink()
            except Exception:
                pass
            self._env_file = None
