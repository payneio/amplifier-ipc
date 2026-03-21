"""BashTool — Execute bash commands with safety features."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
from typing import Any

from amplifier_ipc_protocol import ToolResult

from .safety import SafetyConfig, SafetyValidator

logger = logging.getLogger(__name__)


class BashTool:
    """Execute bash commands with safety features."""

    name = "bash"
    description = """\
Low-level shell command execution. This is a fallback primitive - before using bash directly,
consider whether specialized capabilities exist for your task. Specialized options typically offer
better error handling, structured output, domain expertise, and safety guardrails.

WHEN TO USE BASH:
- Build and test commands (pytest, npm test, cargo build, make)
- Package management (pip, npm, cargo, brew)
- Version control operations (git status, git diff, git commit)
- Container operations (docker, podman, kubectl)
- GitHub CLI (gh pr create, gh issue list)
- System utilities when no specialized option exists

INTRINSIC LIMITATIONS (why specialized options are often better):
- Raw text output requiring manual parsing
- No domain-specific context or best practices built in
- No built-in retry logic or intelligent error recovery
- No semantic understanding of your intent

OUTPUT LIMITS:
- Long outputs are automatically truncated to prevent context overflow
- When truncated, you'll see: first lines, \"[...truncated...]\", last lines, and byte counts
- WARNING: If output contains JSON, XML, or similar structured data, truncation may break parsing
- WORKAROUND: For large structured output, redirect to a file (command > output.json) and use
  file reading capabilities to inspect portions of the file as needed

COMMAND GUIDELINES:
- Quote paths containing spaces: cd \"/path/with spaces\"
- Prefer absolute paths to maintain working directory context
- Chain dependent commands with && (mkdir foo && cd foo)
- Commands time out after 30 seconds by default. Pass `timeout` to increase for long-running
  commands (builds, tests, monitoring). Use `run_in_background` for truly indefinite processes.
- Use `run_in_background` for long-running processes (dev servers, watchers)
- Interactive commands (-i flags, editors requiring input) are not supported

SAFETY:
- Destructive commands (rm -rf /, sudo rm, etc.) are blocked
- Commands requiring interactive input will fail
                   """

    DEFAULT_MAX_OUTPUT_BYTES = 100_000

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize bash tool.

        Args:
            config: Tool configuration
        """
        self.config = config or {}
        self.require_approval = self.config.get("require_approval", True)
        self.timeout = self.config.get("timeout", 30)
        self.working_dir = self.config.get("working_dir", ".")
        self.max_output_bytes = self.config.get(
            "max_output_bytes", self.DEFAULT_MAX_OUTPUT_BYTES
        )

        safety_profile = self.config.get("safety_profile", "strict")
        safety_config = SafetyConfig(
            profile=safety_profile,
            allowed_commands=self.config.get("allowed_commands", []),
            denied_commands=self.config.get("denied_commands", []),
            safety_overrides=self.config.get("safety_overrides"),
        )
        self._safety_validator = SafetyValidator(
            profile=safety_profile, config=safety_config
        )

        self.allowed_commands = self.config.get("allowed_commands", [])
        self.denied_commands = self.config.get("denied_commands", [])

        self._wsl_bash_cache: dict[str, bool] = {}

        self._win_detach_flags: int = getattr(
            subprocess, "DETACHED_PROCESS", 0
        ) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute"},
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds (default: 30).",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run command in background, returning immediately with PID.",
                    "default": False,
                },
            },
            "required": ["command"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a bash command."""
        command = input.get("command")
        if not command:
            error_msg = "Command is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        timeout = input.get("timeout", self.timeout)
        run_in_background = input.get("run_in_background", False)

        safety_result = self._safety_validator.validate(command)
        if not safety_result.allowed:
            error_msg = f"Command denied for safety: {safety_result.reason}"
            if safety_result.hint:
                error_msg += f"\n  Hint: {safety_result.hint}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg},
            )

        try:
            if run_in_background:
                result = await self._run_command_background(command)
                return ToolResult(
                    success=True,
                    output={
                        "pid": result["pid"],
                        "message": f"Command started in background with PID {result['pid']}",
                        "note": "Use 'ps' or 'kill' commands to manage the background process.",
                    },
                )
            else:
                result = await self._run_command(command, timeout=timeout)

                stdout, stdout_truncated, stdout_bytes = self._truncate_output(
                    result["stdout"]
                )
                stderr, stderr_truncated, stderr_bytes = self._truncate_output(
                    result["stderr"]
                )

                output: dict[str, Any] = {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result["returncode"],
                }

                if stdout_truncated or stderr_truncated:
                    output["truncated"] = True
                    if stdout_truncated:
                        output["stdout_total_bytes"] = stdout_bytes
                    if stderr_truncated:
                        output["stderr_total_bytes"] = stderr_bytes

                return ToolResult(
                    success=result["returncode"] == 0,
                    output=output,
                )

        except TimeoutError:
            error_msg = f"Command timed out after {timeout} seconds"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg},
            )
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            error_msg = str(e)
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

    def _extract_head_bytes(self, output: str, budget: int) -> str:
        encoded = output.encode("utf-8")
        if len(encoded) <= budget:
            return output
        truncated_bytes = encoded[:budget]
        for i in range(len(truncated_bytes), max(0, len(truncated_bytes) - 4), -1):
            try:
                return truncated_bytes[:i].decode("utf-8")
            except UnicodeDecodeError:
                continue
        return truncated_bytes.decode("utf-8", errors="ignore")

    def _extract_tail_bytes(self, output: str, budget: int) -> str:
        encoded = output.encode("utf-8")
        if len(encoded) <= budget:
            return output
        truncated_bytes = encoded[-budget:]
        for i in range(min(4, len(truncated_bytes))):
            try:
                return truncated_bytes[i:].decode("utf-8")
            except UnicodeDecodeError:
                continue
        return truncated_bytes.decode("utf-8", errors="ignore")

    def _truncate_output(self, output: str) -> tuple[str, bool, int]:
        original_bytes = len(output.encode("utf-8"))

        if original_bytes <= self.max_output_bytes:
            return output, False, original_bytes

        head_budget = int(self.max_output_bytes * 0.4)
        tail_budget = int(self.max_output_bytes * 0.4)

        lines = output.split("\n")

        head_lines = []
        head_size = 0
        for line in lines:
            line_bytes = len((line + "\n").encode("utf-8"))
            if head_size + line_bytes > head_budget:
                break
            head_lines.append(line)
            head_size += line_bytes

        tail_lines = []
        tail_size = 0
        for line in reversed(lines):
            line_bytes = len((line + "\n").encode("utf-8"))
            if tail_size + line_bytes > tail_budget:
                break
            tail_lines.insert(0, line)
            tail_size += line_bytes

        head_content = "\n".join(head_lines)
        tail_content = "\n".join(tail_lines)

        captured_bytes = len(head_content.encode("utf-8")) + len(
            tail_content.encode("utf-8")
        )
        min_useful = self.max_output_bytes * 0.2

        if captured_bytes < min_useful:
            head_content = self._extract_head_bytes(output, head_budget)
            tail_content = self._extract_tail_bytes(output, tail_budget)

            head_actual_bytes = len(head_content.encode("utf-8"))
            tail_actual_bytes = len(tail_content.encode("utf-8"))

            truncation_indicator = (
                f"\n\n[...OUTPUT TRUNCATED (byte-level)...]\n"
                f"[Showing first ~{head_actual_bytes:,} bytes and last ~{tail_actual_bytes:,} bytes]\n"
                f"[Total output: {original_bytes:,} bytes, limit: {self.max_output_bytes:,} bytes]\n"
                f"[TIP: For large structured output, redirect to file and read portions]\n\n"
            )
        else:
            truncation_indicator = (
                f"\n\n[...OUTPUT TRUNCATED...]\n"
                f"[Showing first {len(head_lines)} lines and last {len(tail_lines)} lines]\n"
                f"[Total output: {original_bytes:,} bytes, limit: {self.max_output_bytes:,} bytes]\n"
                f"[TIP: For large structured output (JSON/XML), redirect to file and read portions]\n\n"
            )

        truncated = head_content + truncation_indicator + tail_content
        return truncated, True, original_bytes

    async def _is_wsl_bash(self, bash_exe: str) -> bool:
        if bash_exe in self._wsl_bash_cache:
            return self._wsl_bash_cache[bash_exe]

        try:
            proc = await asyncio.create_subprocess_exec(
                bash_exe,
                "-c",
                "test -d /mnt/wsl",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=".",
            )
            await asyncio.wait_for(proc.communicate(), timeout=2)
            is_wsl = proc.returncode == 0
            self._wsl_bash_cache[bash_exe] = is_wsl
            return is_wsl
        except Exception:
            self._wsl_bash_cache[bash_exe] = False
            return False

    async def _run_command_background(self, command: str) -> dict[str, Any]:
        """Run command in background, returning immediately with PID."""
        is_windows = sys.platform == "win32"
        devnull = subprocess.DEVNULL

        if is_windows:
            bash_exe = shutil.which("bash")
            if bash_exe:
                is_wsl = self._wsl_bash_cache.get(bash_exe, False)
                if is_wsl:
                    process = subprocess.Popen(
                        ["wsl", "--exec", "bash", "-c", command],
                        stdout=devnull,
                        stderr=devnull,
                        stdin=devnull,
                        cwd=self.working_dir,
                        creationflags=self._win_detach_flags,
                    )
                else:
                    process = subprocess.Popen(
                        [bash_exe, "-c", command],
                        stdout=devnull,
                        stderr=devnull,
                        stdin=devnull,
                        cwd=self.working_dir,
                        creationflags=self._win_detach_flags,
                    )
            else:
                try:
                    args = shlex.split(command)
                except ValueError as e:
                    raise ValueError(f"Invalid command syntax: {e}")

                process = subprocess.Popen(
                    args,
                    stdout=devnull,
                    stderr=devnull,
                    stdin=devnull,
                    cwd=self.working_dir,
                    creationflags=self._win_detach_flags,
                )
        else:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=devnull,
                stderr=devnull,
                stdin=devnull,
                executable="/bin/bash",
                cwd=self.working_dir,
                start_new_session=True,
            )

        return {"pid": process.pid}

    async def _run_command(
        self, command: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Run command asynchronously with platform-appropriate shell."""
        is_windows = sys.platform == "win32"
        process = None
        pgid = None

        if is_windows:
            bash_exe = shutil.which("bash")

            if bash_exe:
                is_wsl = await self._is_wsl_bash(bash_exe)

                if is_wsl:
                    process = await asyncio.create_subprocess_exec(
                        "wsl",
                        "--exec",
                        "bash",
                        "-c",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=self.working_dir,
                    )
                else:
                    process = await asyncio.create_subprocess_exec(
                        bash_exe,
                        "-c",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=self.working_dir,
                    )
            else:
                shell_features = ["|", "&&", "||", "~", ">", "<", "2>&1", "$(", "`"]
                if any(feature in command for feature in shell_features):
                    return {
                        "stdout": "",
                        "stderr": "Bash not found in PATH.",
                        "returncode": 1,
                    }

                try:
                    args = shlex.split(command)
                except ValueError as e:
                    raise ValueError(f"Invalid command syntax: {e}")

                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.working_dir,
                )
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable="/bin/bash",
                cwd=self.working_dir,
                start_new_session=True,
            )
            pgid = process.pid

        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=effective_timeout
            )

            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": process.returncode,
            }

        except TimeoutError:
            if pgid is not None and not is_windows:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                    await asyncio.sleep(0.5)
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except ProcessLookupError:
                    pass
                except PermissionError:
                    process.kill()
            else:
                process.kill()

            try:
                await asyncio.wait_for(process.communicate(), timeout=5)
            except TimeoutError:
                pass
            raise
