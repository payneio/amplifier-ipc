"""WriteTool - Write files to the local filesystem."""

from pathlib import Path
from typing import Any

from amplifier_ipc_protocol import ToolResult

from .path_validation import is_path_allowed


class WriteTool:
    """Write files to the local filesystem."""

    name = "write_file"
    description = """\
Writes a file to the local filesystem.

Usage:
- The file_path parameter accepts:
  - Absolute paths: /home/user/file.md
  - Relative paths: ./docs/README.md
- This tool will overwrite the existing file if there is one at the provided path.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
                   """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize WriteTool with configuration."""
        self.config = config or {}
        self.working_dir = self.config.get("working_dir")
        default_allowed = [self.working_dir] if self.working_dir else ["."]
        self.allowed_write_paths = self.config.get(
            "allowed_write_paths", default_allowed
        )
        self.denied_write_paths = self.config.get("denied_write_paths", [])

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        }

    def _check_write_access(self, path: Path) -> tuple[bool, str | None]:
        """Check if path is allowed for writing."""
        return is_path_allowed(path, self.allowed_write_paths, self.denied_write_paths)

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Write content to a file."""
        file_path = input.get("file_path", "")
        content = input.get("content", "")

        if not file_path:
            error_msg = "file_path is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        path = Path(file_path).expanduser()
        if not path.is_absolute() and self.working_dir:
            path = Path(self.working_dir) / path

        allowed, error_msg = self._check_write_access(path)
        if not allowed:
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            bytes_written = len(content.encode("utf-8"))

            return ToolResult(
                success=True, output={"file_path": str(path), "bytes": bytes_written}
            )

        except OSError as e:
            error_msg = f"OS error writing file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": "OSError", "errno": e.errno},
            )
        except Exception as e:
            error_msg = f"Error writing file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": type(e).__name__},
            )
