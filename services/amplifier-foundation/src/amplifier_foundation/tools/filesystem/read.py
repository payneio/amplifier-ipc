"""ReadTool - Read files from the local filesystem."""

from pathlib import Path
from typing import Any

from amplifier_ipc.protocol import ToolResult


class ReadTool:
    """Read files from the local filesystem with line numbering and pagination support."""

    name = "read_file"
    description = """\
Reads a file or lists a directory from the local filesystem. You can access any file directly by using this tool.

Usage:
- The file_path parameter accepts:
  - Absolute paths: /home/user/file.md
  - Relative paths: ./docs/README.md
- By default, reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files)
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- For directories, returns a formatted listing showing DIR/FILE entries
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize ReadTool with configuration."""
        self.config = config or {}
        self.allowed_read_paths = self.config.get("allowed_read_paths")
        self.max_line_length = 2000
        self.default_line_limit = 2000
        self.working_dir = self.config.get("working_dir")

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file/directory to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "The line number to start reading from (1-indexed).",
                },
                "limit": {
                    "type": "integer",
                    "description": "The number of lines to read.",
                },
            },
            "required": ["file_path"],
        }

    def _is_allowed(self, path: Path) -> bool:
        """Check if path is within allowed read paths."""
        if self.allowed_read_paths is None:
            return True

        resolved_path = path.resolve()
        for allowed in self.allowed_read_paths:
            allowed_resolved = Path(allowed).resolve()
            if (
                allowed_resolved in resolved_path.parents
                or allowed_resolved == resolved_path
            ):
                return True
        return False

    def _format_with_line_numbers(self, lines: list[str], start_line: int) -> str:
        """Format lines with line numbers in cat -n style."""
        formatted_lines = []
        for i, line in enumerate(lines, start=start_line):
            if len(line) > self.max_line_length:
                line = line[: self.max_line_length] + "... [truncated]"
            formatted_lines.append(f"{i:6d}\t{line}")
        return "\n".join(formatted_lines)

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Read a file or directory from the filesystem."""
        file_path = input.get("file_path", "")
        offset = input.get("offset", 1)
        limit = input.get("limit", self.default_line_limit)

        if not file_path:
            error_msg = "file_path is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        path = Path(file_path).expanduser()
        if not path.is_absolute() and self.working_dir:
            path = Path(self.working_dir) / path

        if not self._is_allowed(path):
            error_msg = f"Access denied: {file_path} is not within allowed read paths"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg},
            )

        if not path.exists():
            error_msg = f"Path not found: {file_path}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        if path.is_dir():
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
                lines = []
                for entry in entries:
                    entry_type = "DIR " if entry.is_dir() else "FILE"
                    lines.append(f"  {entry_type} {entry.name}")

                listing = "\n".join(lines)
                output_text = f"Directory: {path}\n\n{listing}"

                return ToolResult(
                    success=True,
                    output={
                        "file_path": str(path),
                        "content": output_text,
                        "is_directory": True,
                        "entry_count": len(entries),
                    },
                )
            except Exception as e:
                error_msg = f"Error listing directory: {str(e)}"
                return ToolResult(
                    success=False,
                    output=error_msg,
                    error={"message": error_msg, "type": type(e).__name__},
                )

        try:
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()

            start_idx = max(0, offset - 1)
            end_idx = start_idx + limit

            selected_lines = lines[start_idx:end_idx]

            formatted_content = self._format_with_line_numbers(
                selected_lines, start_line=offset
            )

            output: dict[str, Any] = {
                "file_path": str(path),
                "content": formatted_content,
                "total_lines": len(lines),
                "lines_read": len(selected_lines),
                "offset": offset,
            }

            if len(lines) == 0:
                output["warning"] = "File exists but has empty contents"

            return ToolResult(success=True, output=output)

        except UnicodeDecodeError:
            error_msg = (
                f"Cannot read file: {file_path} (not a text file or encoding issue)"
            )
            return ToolResult(
                success=False,
                output=error_msg,
                error={
                    "message": error_msg,
                    "type": "UnicodeDecodeError",
                },
            )
        except Exception as e:
            error_msg = f"Error reading file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": type(e).__name__},
            )
