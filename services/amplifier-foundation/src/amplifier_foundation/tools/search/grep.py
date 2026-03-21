"""GrepTool - Search file contents with regex patterns using ripgrep or Python re."""

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from amplifier_ipc_protocol import ToolResult

from ._defaults import DEFAULT_EXCLUSIONS as _DEFAULT_EXCLUSIONS

logger = logging.getLogger(__name__)


class GrepTool:
    """Search file contents with regex patterns using ripgrep (fast) or Python re (fallback)."""

    name = "grep"
    description = r"""
Search file contents with regex patterns. Uses ripgrep when available (fast), falls back to Python re.

CAPABILITIES:
- Full regex syntax (e.g., "log.*Error", "function\s+\w+")
- Filter by glob pattern (e.g., "*.js", "**/*.tsx") or file type (e.g., "py", "js", "rust")
- Output modes: "files_with_matches" (default), "content" (with line content), "count"
- Multiline matching with `multiline: true` for patterns spanning lines

SCOPE AND LIMITS:
- By default, excludes common non-source directories: node_modules, .venv, .git, __pycache__, build dirs
- Results are limited by default (200 files/counts, 500 content matches) to prevent context overflow
- Set `include_ignored: true` to search excluded directories
- Set explicit `head_limit: 0` for unlimited results (use with caution on large codebases)

PATTERN SYNTAX:
- Uses ripgrep regex (not grep) - literal braces need escaping: `interface\{\}` to find `interface{}`
- Case insensitive: use `-i: true`
- Context lines: use `-A`, `-B`, or `-C` parameters with content mode

PAGINATION:
- Use `head_limit` and `offset` for pagination
- Response includes `total_matches` to know how many exist beyond the limit
"""

    DEFAULT_EXCLUSIONS = _DEFAULT_EXCLUSIONS

    DEFAULT_LIMITS = {
        "files_with_matches": 200,
        "content": 500,
        "count": 200,
    }

    TYPE_TO_GLOB = {
        "py": "*.py",
        "js": "*.js",
        "ts": "*.ts",
        "tsx": "*.tsx",
        "jsx": "*.jsx",
        "go": "*.go",
        "rust": "*.rs",
        "java": "*.java",
        "c": "*.c",
        "cpp": "*.cpp",
        "h": "*.h",
        "hpp": "*.hpp",
        "rb": "*.rb",
        "php": "*.php",
        "sh": "*.sh",
        "md": "*.md",
        "json": "*.json",
        "yaml": "*.yaml",
        "yml": "*.yml",
        "toml": "*.toml",
        "xml": "*.xml",
        "html": "*.html",
        "css": "*.css",
    }

    TYPE_ALIASES = {
        "typescript": "ts",
        "javascript": "js",
        "python": "py",
        "ruby": "rb",
        "markdown": "md",
        "shell": "sh",
        "bash": "sh",
        "csharp": "cs",
        "c#": "cs",
        "c++": "cpp",
        "cplusplus": "cpp",
        "golang": "go",
        "rs": "rust",
        "yml": "yaml",
        "tsx": "ts",
        "jsx": "js",
    }

    KNOWN_RG_TYPES = {
        "c",
        "cpp",
        "cs",
        "css",
        "go",
        "h",
        "hpp",
        "html",
        "java",
        "js",
        "json",
        "lua",
        "md",
        "php",
        "py",
        "rb",
        "rust",
        "sh",
        "sql",
        "swift",
        "toml",
        "ts",
        "txt",
        "xml",
        "yaml",
    }

    DEFAULT_TIMEOUT = 60

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize GrepTool with configuration."""
        self.config = config or {}
        self.max_file_size = self.config.get("max_file_size", 10 * 1024 * 1024)
        self.working_dir = self.config.get("working_dir", ".")
        self.timeout = self.config.get("timeout", self.DEFAULT_TIMEOUT)
        self.exclusions = self.config.get("exclusions", self.DEFAULT_EXCLUSIONS)
        self.default_limits = {
            **self.DEFAULT_LIMITS,
            **self.config.get("default_limits", {}),
        }

        rg_path = shutil.which("rg")
        if rg_path:
            self.rg_path: str = rg_path
            self.use_ripgrep = True
        else:
            self.rg_path = ""
            self.use_ripgrep = False

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regular expression pattern to search for in file contents",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in. Defaults to current working directory.",
                },
                "output_mode": {
                    "type": "string",
                    "description": 'Output mode: "content", "files_with_matches", or "count".',
                    "enum": ["content", "files_with_matches", "count"],
                },
                "-i": {"type": "boolean", "description": "Case insensitive search"},
                "-n": {"type": "boolean", "description": "Show line numbers in output"},
                "-A": {
                    "type": "integer",
                    "description": "Lines to show after each match",
                },
                "-B": {
                    "type": "integer",
                    "description": "Lines to show before each match",
                },
                "-C": {
                    "type": "integer",
                    "description": "Lines before and after each match",
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter files",
                },
                "type": {"type": "string", "description": "File type to search"},
                "multiline": {
                    "type": "boolean",
                    "description": "Enable multiline mode",
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Limit output to first N entries",
                },
                "offset": {"type": "integer", "description": "Skip first N entries"},
                "include_ignored": {
                    "type": "boolean",
                    "description": "Search excluded directories",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Search for pattern in files."""
        if self.use_ripgrep:
            return await self._execute_ripgrep(input)
        return await self._execute_python(input)

    async def _execute_ripgrep(self, input: dict[str, Any]) -> ToolResult:
        """Execute search using ripgrep binary (fast path)."""
        pattern: str = input.get("pattern", "")
        if not pattern:
            error_msg = "Pattern is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        cmd = [self.rg_path]

        output_mode = input.get("output_mode", "files_with_matches")
        if output_mode == "files_with_matches":
            cmd.append("--files-with-matches")
        elif output_mode == "count":
            cmd.append("--count")

        if input.get("-i", False):
            cmd.append("-i")

        if output_mode == "content" and input.get("-n", True):
            cmd.append("-n")

        if output_mode == "content":
            if "-C" in input:
                cmd.extend(["-C", str(input["-C"])])
            else:
                if "-A" in input:
                    cmd.extend(["-A", str(input["-A"])])
                if "-B" in input:
                    cmd.extend(["-B", str(input["-B"])])

        if input.get("multiline", False):
            cmd.extend(["-U", "--multiline-dotall"])

        if "glob" in input:
            cmd.extend(["--glob", input["glob"]])
        if "type" in input:
            file_type = input["type"].lower()
            file_type = self.TYPE_ALIASES.get(file_type, file_type)

            if file_type in self.KNOWN_RG_TYPES:
                cmd.extend(["--type", file_type])
            elif file_type in self.TYPE_TO_GLOB:
                cmd.extend(["--glob", self.TYPE_TO_GLOB[file_type]])
            else:
                known_types = sorted(self.KNOWN_RG_TYPES)
                aliases = sorted(self.TYPE_ALIASES.keys())
                return ToolResult(
                    success=False,
                    error={
                        "message": f"Unrecognized file type: '{input['type']}'. "
                        f"Valid types: {', '.join(known_types)}. "
                        f"Also accepts aliases: {', '.join(aliases[:8])}..."
                    },
                )

        if not input.get("include_ignored", False):
            for exclusion in self.exclusions:
                cmd.extend(["--glob", f"!{exclusion}/**"])
                cmd.extend(["--glob", f"!**/{exclusion}/**"])

        cmd.extend(["--max-filesize", str(self.max_file_size)])

        if output_mode == "content":
            cmd.append("--json")

        cmd.append(pattern)

        search_path = input.get("path", ".")
        path_obj = Path(search_path).expanduser()
        if not path_obj.is_absolute():
            search_path = str(Path(self.working_dir) / search_path)
        cmd.append(search_path)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )

            if result.returncode not in [0, 1]:
                error_msg = (
                    result.stderr.strip() if result.stderr else "Unknown ripgrep error"
                )
                return ToolResult(
                    success=False, output=error_msg, error={"message": error_msg}
                )

            output: dict[str, Any] = {
                "pattern": pattern,
                "output_mode": output_mode,
            }

            if output_mode == "content":
                lines = (
                    result.stdout.strip().split("\n") if result.stdout.strip() else []
                )
                matches = []
                for line in lines:
                    if not line:
                        continue
                    try:
                        match_data = json.loads(line)
                        if match_data.get("type") == "match":
                            matches.append(match_data["data"])
                    except json.JSONDecodeError:
                        continue

                formatted_results = []
                for match in matches:
                    path_val = match.get("path", {}).get("text", "")
                    lines_data = match.get("lines", {})
                    line_number = match.get("line_number")
                    formatted_results.append(
                        {
                            "file": path_val,
                            "line_number": line_number,
                            "content": lines_data.get("text", "").rstrip(),
                        }
                    )

                total_matches = len(formatted_results)
                offset = input.get("offset", 0)
                head_limit = input.get("head_limit")
                if head_limit is None:
                    head_limit = self.default_limits.get("content", 500)

                if offset > 0:
                    formatted_results = formatted_results[offset:]
                if head_limit > 0:
                    formatted_results = formatted_results[:head_limit]

                output["total_matches"] = total_matches
                output["matches_count"] = len(formatted_results)
                output["results"] = formatted_results
                if total_matches > len(formatted_results):
                    output["results_capped"] = True

            elif output_mode == "files_with_matches":
                files = [
                    line.strip()
                    for line in result.stdout.strip().split("\n")
                    if line.strip()
                ]
                total_files = len(files)

                offset = input.get("offset", 0)
                head_limit = input.get("head_limit")
                if head_limit is None:
                    head_limit = self.default_limits.get("files_with_matches", 200)

                if offset > 0:
                    files = files[offset:]
                if head_limit > 0:
                    files = files[:head_limit]

                output["total_matches"] = total_files
                output["matches_count"] = len(files)
                output["files"] = files
                if total_files > len(files):
                    output["results_capped"] = True

            elif output_mode == "count":
                lines = [
                    line.strip()
                    for line in result.stdout.strip().split("\n")
                    if line.strip()
                ]
                all_counts: dict[str, int] = {}
                for line in lines:
                    if ":" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            filepath, count_str = parts
                            try:
                                all_counts[filepath] = int(count_str)
                            except ValueError:
                                continue

                total_matches_sum = sum(all_counts.values())
                offset = input.get("offset", 0)
                head_limit = input.get("head_limit")
                if head_limit is None:
                    head_limit = self.default_limits.get("count", 200)

                count_items = list(all_counts.items())
                if offset > 0:
                    count_items = count_items[offset:]
                if head_limit > 0:
                    count_items = count_items[:head_limit]
                counts = dict(count_items)

                output["total_matches"] = total_matches_sum
                output["matches_count"] = sum(counts.values())
                output["counts"] = counts
                if len(all_counts) > len(counts):
                    output["results_capped"] = True

            return ToolResult(success=True, output=output)

        except subprocess.TimeoutExpired:
            error_msg = "Search timed out. Try narrowing your search or using more specific patterns."
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

    async def _execute_python(self, input: dict[str, Any]) -> ToolResult:
        """Execute search using Python re module (fallback path)."""
        pattern = input.get("pattern")
        if not pattern:
            error_msg = "Pattern is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        search_path = input.get("path", ".")
        output_mode = input.get("output_mode", "files_with_matches")
        ignore_case = input.get("-i", False)
        show_line_numbers = input.get("-n", True) and output_mode == "content"
        multiline = input.get("multiline", False)

        context_after = input.get("-A", 0) if output_mode == "content" else 0
        context_before = input.get("-B", 0) if output_mode == "content" else 0
        if "-C" in input and output_mode == "content":
            context_after = context_before = input["-C"]

        glob_pattern = input.get("glob", "**/*")
        if "type" in input:
            file_type = input["type"].lower()
            file_type = self.TYPE_ALIASES.get(file_type) or file_type
            type_glob = self.TYPE_TO_GLOB.get(file_type)
            if type_glob:
                glob_pattern = f"**/{type_glob}"
            elif file_type not in self.KNOWN_RG_TYPES:
                known_types = sorted(self.KNOWN_RG_TYPES)
                aliases = sorted(self.TYPE_ALIASES.keys())
                return ToolResult(
                    success=False,
                    error={
                        "message": f"Unrecognized file type: '{input['type']}'. "
                        f"Valid types: {', '.join(known_types)}. "
                        f"Also accepts aliases: {', '.join(aliases[:8])}..."
                    },
                )

        try:
            flags = 0
            if ignore_case:
                flags |= re.IGNORECASE
            if multiline:
                flags |= re.MULTILINE | re.DOTALL

            regex = re.compile(pattern, flags)

            path_obj = Path(search_path).expanduser()
            if not path_obj.is_absolute():
                path = Path(self.working_dir) / search_path
            else:
                path = path_obj
            if not path.exists():
                error_msg = f"Path not found: {search_path}"
                return ToolResult(
                    success=False, output=error_msg, error={"message": error_msg}
                )

            include_ignored = input.get("include_ignored", False)
            files = self._find_files(path, glob_pattern, include_ignored)

            output: dict[str, Any] = {
                "pattern": pattern,
                "output_mode": output_mode,
            }

            if output_mode == "content":
                all_results = []
                for file_path in files:
                    matches = self._search_file_content(
                        file_path,
                        regex,
                        show_line_numbers,
                        context_before,
                        context_after,
                    )
                    all_results.extend(matches)

                total_matches = len(all_results)
                offset = input.get("offset", 0)
                head_limit = input.get("head_limit")
                if head_limit is None:
                    head_limit = self.default_limits.get("content", 500)
                if offset > 0:
                    all_results = all_results[offset:]
                if head_limit > 0:
                    all_results = all_results[:head_limit]

                output["total_matches"] = total_matches
                output["matches_count"] = len(all_results)
                output["results"] = all_results
                if total_matches > len(all_results):
                    output["results_capped"] = True

            elif output_mode == "files_with_matches":
                matched_files = []
                for file_path in files:
                    if self._file_has_match(file_path, regex):
                        matched_files.append(str(file_path))

                total_files = len(matched_files)
                offset = input.get("offset", 0)
                head_limit = input.get("head_limit")
                if head_limit is None:
                    head_limit = self.default_limits.get("files_with_matches", 200)
                if offset > 0:
                    matched_files = matched_files[offset:]
                if head_limit > 0:
                    matched_files = matched_files[:head_limit]

                output["total_matches"] = total_files
                output["matches_count"] = len(matched_files)
                output["files"] = matched_files
                if total_files > len(matched_files):
                    output["results_capped"] = True

            elif output_mode == "count":
                all_counts: dict[str, int] = {}
                for file_path in files:
                    count = self._count_matches(file_path, regex)
                    if count > 0:
                        all_counts[str(file_path)] = count

                total_matches_sum = sum(all_counts.values())
                offset = input.get("offset", 0)
                head_limit = input.get("head_limit")
                if head_limit is None:
                    head_limit = self.default_limits.get("count", 200)
                count_items = list(all_counts.items())
                if offset > 0:
                    count_items = count_items[offset:]
                if head_limit > 0:
                    count_items = count_items[:head_limit]
                counts = dict(count_items)

                output["total_matches"] = total_matches_sum
                output["matches_count"] = sum(counts.values())
                output["counts"] = counts
                if len(all_counts) > len(counts):
                    output["results_capped"] = True

            return ToolResult(success=True, output=output)

        except re.error as e:
            error_msg = f"Invalid regex pattern: {e}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

    def _find_files(
        self, path: Path, glob_pattern: str, include_ignored: bool = False
    ) -> list[Path]:
        """Find files matching glob pattern, respecting exclusions."""
        files = []

        if path.is_file():
            return [path]

        try:
            for file_path in path.glob(glob_pattern):
                if not file_path.is_file():
                    continue

                if not include_ignored:
                    path_str = str(file_path)
                    skip = False
                    for exclusion in self.exclusions:
                        if f"/{exclusion}/" in path_str or path_str.endswith(
                            f"/{exclusion}"
                        ):
                            skip = True
                            break
                    if skip:
                        continue

                try:
                    if file_path.stat().st_size > self.max_file_size:
                        continue
                except OSError:
                    continue

                try:
                    with open(file_path, "rb") as f:
                        chunk = f.read(8192)
                        if b"\x00" in chunk:
                            continue
                except OSError:
                    continue

                files.append(file_path)
        except Exception as e:
            logger.debug("Error scanning files under %s: %s", path, e)

        return files

    def _file_has_match(self, file_path: Path, regex: re.Pattern[str]) -> bool:
        """Check if file contains any match."""
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                return regex.search(content) is not None
        except Exception as e:
            logger.debug("Error reading %s for match check: %s", file_path, e)
            return False

    def _count_matches(self, file_path: Path, regex: re.Pattern[str]) -> int:
        """Count number of matches in file."""
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                return len(regex.findall(content))
        except Exception as e:
            logger.debug("Error reading %s for match count: %s", file_path, e)
            return 0

    def _search_file_content(
        self,
        file_path: Path,
        regex: re.Pattern[str],
        show_line_numbers: bool,
        context_before: int,
        context_after: int,
    ) -> list[dict[str, Any]]:
        """Search file and return matches with context."""
        results = []

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    result: dict[str, Any] = {
                        "file": str(file_path),
                        "content": line.rstrip(),
                    }

                    if show_line_numbers:
                        result["line_number"] = i

                    if context_before > 0 or context_after > 0:
                        start_idx = max(0, i - context_before - 1)
                        end_idx = min(len(lines), i + context_after)

                        context_lines = []
                        for j in range(start_idx, end_idx):
                            context_lines.append(
                                {
                                    "line_number": j + 1,
                                    "content": lines[j].rstrip(),
                                    "is_match": (j + 1) == i,
                                }
                            )

                        result["context"] = context_lines

                    results.append(result)

        except Exception as e:
            logger.debug("Error reading %s for content search: %s", file_path, e)

        return results
