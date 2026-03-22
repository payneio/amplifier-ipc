"""GlobTool - Find files matching glob patterns."""

from pathlib import Path
from typing import Any

from amplifier_ipc.protocol import ToolResult

from ._defaults import DEFAULT_EXCLUSIONS as _DEFAULT_EXCLUSIONS


class GlobTool:
    """Find files matching glob patterns."""

    name = "glob"
    description = """\
- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns

SCOPE AND LIMITS:
- By default, excludes common non-source directories: node_modules, .venv, .git, __pycache__, build dirs
- Results are limited to 500 files by default to prevent context overflow
- Set `include_ignored: true` to search excluded directories
- Response includes `total_files` to know if results were capped
                   """

    DEFAULT_EXCLUSIONS = _DEFAULT_EXCLUSIONS

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize GlobTool with configuration."""
        self.config = config or {}
        self.max_results = self.config.get("max_results", 500)
        self.allowed_paths = self.config.get("allowed_paths", ["."])
        self.working_dir = self.config.get("working_dir", ".")
        self.exclusions = self.config.get("exclusions", self.DEFAULT_EXCLUSIONS)

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '**/*.py')",
                },
                "path": {
                    "type": "string",
                    "description": "Base path to search from (default: current directory)",
                },
                "type": {
                    "type": "string",
                    "enum": ["file", "dir", "any"],
                    "description": "Filter by type: file, dir, or any (default: file)",
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns to exclude from results",
                },
                "include_ignored": {
                    "type": "boolean",
                    "description": "Search in normally-excluded directories. Default: false.",
                },
            },
            "required": ["pattern"],
        }

    def _is_excluded(self, path_str: str) -> bool:
        """Check if a path should be excluded based on exclusion patterns."""
        for exclusion in self.exclusions:
            if (
                f"/{exclusion}/" in path_str
                or f"/{exclusion}" in path_str
                or path_str.startswith(f"{exclusion}/")
            ):
                return True
        return False

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Find files matching pattern."""
        pattern = input.get("pattern")
        base_path = input.get("path", ".")
        filter_type = input.get("type", "any")
        exclude_patterns = input.get("exclude", [])
        include_ignored = input.get("include_ignored", False)

        if not pattern:
            error_msg = "Pattern is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        try:
            path_obj = Path(base_path).expanduser()
            if not path_obj.is_absolute():
                path = Path(self.working_dir) / base_path
            else:
                path = path_obj
            if not path.exists():
                error_msg = f"Path not found: {base_path}"
                return ToolResult(
                    success=False, output=error_msg, error={"message": error_msg}
                )

            all_matches: list[dict[str, Any]] = []
            for match_path in path.glob(pattern):
                match_path_str = str(match_path)

                if not include_ignored and self._is_excluded(match_path_str):
                    continue

                if (
                    filter_type == "file"
                    and not match_path.is_file()
                    or filter_type == "dir"
                    and not match_path.is_dir()
                ):
                    continue

                excluded = False
                for exclude_pattern in exclude_patterns:
                    if match_path.match(exclude_pattern):
                        excluded = True
                        break

                if not excluded:
                    try:
                        stat = match_path.stat()
                        match_info: dict[str, Any] = {
                            "path": match_path_str,
                            "type": "file" if match_path.is_file() else "dir",
                            "mtime": stat.st_mtime,
                        }
                        if match_path.is_file():
                            match_info["size"] = stat.st_size
                        else:
                            match_info["size"] = None

                        all_matches.append(match_info)
                    except OSError:
                        continue

            total_files = len(all_matches)
            all_matches.sort(key=lambda m: m["mtime"], reverse=True)
            matches = all_matches[: self.max_results]

            for match in matches:
                del match["mtime"]

            output: dict[str, Any] = {
                "pattern": pattern,
                "base_path": str(path),
                "total_files": total_files,
                "count": len(matches),
                "matches": matches,
            }

            if total_files > len(matches):
                output["results_capped"] = True

            return ToolResult(success=True, output=output)

        except Exception as e:
            error_msg = f"Glob search failed: {e}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )
