"""Status context hook — injects git/system status before each LLM request."""

from __future__ import annotations

import fnmatch
import logging
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol import hook
from amplifier_ipc_protocol.models import HookAction, HookResult

logger = logging.getLogger(__name__)

# Tier 1: Always ignore (DoS prevention)
DEFAULT_TIER1_PATTERNS = [
    "node_modules/**",
    ".npm/**",
    ".yarn/**",
    ".pnpm-store/**",
    ".venv/**",
    "venv/**",
    "env/**",
    "ENV/**",
    "__pycache__/**",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "build/**",
    "dist/**",
    "out/**",
    "target/**",
    "bin/**",
    "obj/**",
    ".git/**",
]

# Tier 2: Limit with context
DEFAULT_TIER2_PATTERNS = [
    "*.lock",
    "*.sum",
    "yarn.lock",
    "package-lock.json",
    "Gemfile.lock",
    ".idea/**",
    ".vscode/**",
    "*.swp",
    "*.swo",
    "*.log",
    "logs/**",
    "coverage/**",
    ".coverage",
    "*.min.js",
    "*.min.css",
    "*.map",
]


@hook(events=["provider:request"], priority=0)
class StatusContextHook:
    """Injects status context (git, datetime) before each LLM request.

    Self-contained — does not require session access.
    """

    name = "status_context"
    events = ["provider:request"]
    priority = 0

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.working_dir = "."

        # Git context options
        self.include_git = True
        self.git_include_status = True
        self.git_include_commits = 5
        self.git_include_branch = True
        self.git_include_main_branch = True

        # Git status truncation options
        self.git_status_include_untracked = True
        self.git_status_max_untracked = 20
        self.git_status_max_lines = 100

        # Tier-based filtering
        self.git_status_enable_path_filtering = True
        self.tier1_patterns = list(DEFAULT_TIER1_PATTERNS)
        self.tier2_patterns = list(DEFAULT_TIER2_PATTERNS)
        self.git_status_tier2_limit = 10

        # Hard limits
        self.git_status_max_tracked = 50

        # Filtering messages
        self.git_status_show_filter_summary = True

        # Datetime options
        self.include_datetime = True
        self.datetime_include_timezone = False

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Inject status context before provider request."""
        if event == "provider:request":
            return await self._on_provider_request(event, data)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_provider_request(
        self, _event: str, _data: dict[str, Any]
    ) -> HookResult:
        """Gather environment and git info and inject as context."""
        env_info = self._gather_env_info()

        git_details = None
        if self.include_git and env_info.get("is_git_repo"):
            git_details = self._gather_git_context()

        context_parts = [env_info["formatted"]]
        if git_details:
            context_parts.append(git_details)

        context_content = "\n\n".join(context_parts)
        behavioral_note = (
            "\n\nThis context is for your reference only. DO NOT mention this "
            "status information to the user unless directly relevant to their "
            "question. Process silently and continue your work."
        )
        context_injection = (
            f'<system-reminder source="hooks-status-context">\n'
            f"{context_content}{behavioral_note}\n"
            f"</system-reminder>"
        )

        return HookResult(
            action=HookAction.INJECT_CONTEXT,
            context_injection=context_injection,
            context_injection_role="user",
            ephemeral=True,
        )

    def _resolve_working_dir(self) -> str:
        """Resolve self.working_dir to an absolute path string."""
        working_dir_path = Path(self.working_dir)
        if not working_dir_path.is_absolute():
            return str(Path.cwd() / working_dir_path)
        return str(working_dir_path)

    def _gather_env_info(self) -> dict[str, Any]:
        """Gather environment information."""
        try:
            working_dir = self._resolve_working_dir()
            is_git_repo = self._run_git(["rev-parse", "--git-dir"]) is not None
            platform_name = platform.system().lower()
            os_version = platform.platform()

            now = datetime.now()
            if self.include_datetime:
                if self.datetime_include_timezone:
                    timezone_name = now.astimezone().tzname()
                    date_str = f"{now.strftime('%Y-%m-%d %H:%M:%S')} {timezone_name}"
                else:
                    date_str = f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                date_str = now.strftime("%Y-%m-%d")

            env_lines = [
                "Here is useful information about the environment you are running in:",
                "<env>",
                f"Working directory: {working_dir}",
                f"Is directory a git repo: {'Yes' if is_git_repo else 'No'}",
                f"Platform: {platform_name}",
                f"OS Version: {os_version}",
                f"Today's date: {date_str}",
                "</env>",
            ]

            return {
                "working_dir": working_dir,
                "is_git_repo": is_git_repo,
                "platform": platform_name,
                "os_version": os_version,
                "date": date_str,
                "formatted": "\n".join(env_lines),
            }

        except Exception as e:
            logger.warning("Failed to gather environment info: %s", e)
            return {
                "working_dir": self._resolve_working_dir(),
                "is_git_repo": False,
                "platform": "unknown",
                "os_version": "unknown",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "formatted": (
                    "Here is useful information about the environment you are running in:\n"
                    "<env>\nEnvironment information unavailable\n</env>"
                ),
            }

    def _gather_git_context(self) -> str | None:
        """Gather current git repository context."""
        try:
            parts = [
                "gitStatus: This is the git status at the start of the conversation. "
                "Note that this status is a snapshot in time, and will not update during the conversation."
            ]

            if self.git_include_branch:
                branch = self._run_git(["branch", "--show-current"])
                if branch:
                    parts.append(f"Current branch: {branch}")

            if self.git_include_main_branch:
                for main_branch in ["main", "master"]:
                    result = self._run_git(["rev-parse", "--verify", main_branch])
                    if result is not None:
                        parts.append(
                            f"\nMain branch (you will usually use this for PRs): {main_branch}"
                        )
                        break

            if self.git_include_status:
                status = self._gather_git_status()
                if status:
                    parts.append(f"\nStatus:\n{status}")

            if self.git_include_commits and self.git_include_commits > 0:
                log = self._run_git(
                    ["log", "--oneline", f"-{self.git_include_commits}"]
                )
                if log:
                    parts.append(f"\nRecent commits:\n{log}")

            return "\n".join(parts) if len(parts) > 1 else None

        except Exception as e:
            logger.warning("Failed to gather git context: %s", e)
            return None

    def _matches_tier(self, filepath: str, patterns: list[str]) -> bool:
        """Check if filepath matches any pattern in the list."""
        for pattern in patterns:
            if pattern.endswith("/**"):
                prefix = pattern[:-3]
                if filepath.startswith(prefix):
                    return True
            elif fnmatch.fnmatch(filepath, pattern):
                return True
        return False

    def _classify_status_line(self, line: str) -> tuple[str, str, str]:
        """Classify git status line into tier."""
        status_code = line[:2].strip()
        filepath = line[3:].strip() if len(line) > 3 else ""

        if not self.git_status_enable_path_filtering:
            return ("tier3", filepath, status_code)

        if self._matches_tier(filepath, self.tier1_patterns):
            return ("tier1", filepath, status_code)

        if self._matches_tier(filepath, self.tier2_patterns):
            return ("tier2", filepath, status_code)

        return ("tier3", filepath, status_code)

    def _gather_git_status(self) -> str | None:
        """Get git status with tier-based path filtering."""
        raw_status = self._run_git(["status", "--short"])
        if not raw_status:
            return "Working directory clean"

        tier1_tracked: list[str] = []
        tier1_untracked: list[str] = []
        tier2_lines: list[str] = []
        tier3_tracked: list[str] = []
        tier3_untracked: list[str] = []

        for line in raw_status.splitlines():
            tier, filepath, status = self._classify_status_line(line)

            if tier == "tier1":
                if status == "??":
                    tier1_untracked.append(line)
                else:
                    tier1_tracked.append(line)
            elif tier == "tier2":
                tier2_lines.append(line)
            else:
                if status == "??":
                    tier3_untracked.append(line)
                else:
                    tier3_tracked.append(line)

        result: list[str] = []

        if len(tier3_tracked) <= self.git_status_max_tracked:
            result.extend(tier3_tracked)
        else:
            result.extend(tier3_tracked[: self.git_status_max_tracked])
            omitted = len(tier3_tracked) - self.git_status_max_tracked
            if self.git_status_show_filter_summary:
                result.append(f"... ({omitted} more tracked files omitted)")

        if self.git_status_include_untracked:
            if len(tier3_untracked) <= self.git_status_max_untracked:
                result.extend(tier3_untracked)
            else:
                result.extend(tier3_untracked[: self.git_status_max_untracked])
                omitted = len(tier3_untracked) - self.git_status_max_untracked
                if self.git_status_show_filter_summary:
                    result.append(f"... ({omitted} more untracked files omitted)")

        if len(tier2_lines) <= self.git_status_tier2_limit:
            result.extend(tier2_lines)
        else:
            result.extend(tier2_lines[: self.git_status_tier2_limit])
            omitted = len(tier2_lines) - self.git_status_tier2_limit
            if self.git_status_show_filter_summary:
                result.append(f"... ({omitted} more support files omitted)")

        if (
            result
            and self.git_status_show_filter_summary
            and (tier1_tracked or tier1_untracked)
        ):
            result.append("")

        if self.git_status_show_filter_summary:
            if tier1_tracked:
                result.append(
                    f"[WARNING: {len(tier1_tracked)} tracked files in ignored paths]"
                )
                for ex in tier1_tracked[:3]:
                    result.append(f"  {ex}")
                if len(tier1_tracked) > 3:
                    result.append(f"  ... and {len(tier1_tracked) - 3} more")
                result.append("[Suggestion: These directories should not be tracked]")

            if tier1_untracked:
                result.append(
                    f"[Filtered: {len(tier1_untracked)} untracked files in ignored paths]"
                )

        if len(result) > self.git_status_max_lines:
            result = result[: self.git_status_max_lines]
            result.append(
                f"[Hard limit reached: output truncated to {self.git_status_max_lines} lines]"
            )

        return "\n".join(result) if result else "Working directory clean"

    def _run_git(self, args: list[str], timeout: float = 1.0) -> str | None:
        """Run a git command and return output."""
        try:
            working_dir_path = Path(self.working_dir)
            if not working_dir_path.is_absolute():
                cwd = Path.cwd() / working_dir_path
            else:
                cwd = working_dir_path

            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None
