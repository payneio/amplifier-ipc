"""EditTool - Perform exact string replacements in files."""

from pathlib import Path
from typing import Any

from amplifier_ipc.protocol import ToolResult
from amplifier_ipc_protocol.events import ARTIFACT_WRITE

from .path_validation import is_path_allowed


class EditTool:
    """Perform exact string replacements in files."""

    name = "edit_file"
    description = """\
Performs exact string replacements in files.

Usage:
- The file_path parameter accepts:
  - Absolute paths: /home/user/file.md
  - Relative paths: ./docs/README.md
- The edit_file will FAIL if `old_string` is not unique in the file. Either provide a larger
  string with more surrounding context to make it unique or use `replace_all` to change every
  instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize EditTool with configuration."""
        self.config = config or {}
        self.working_dir = self.config.get("working_dir")
        default_allowed = [self.working_dir] if self.working_dir else ["."]
        self.allowed_write_paths = self.config.get(
            "allowed_write_paths", default_allowed
        )
        self.denied_write_paths = self.config.get("denied_write_paths", [])
        self.client: Any = None

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to modify",
                },
                "old_string": {
                    "type": "string",
                    "description": "The text to replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The text to replace it with (must be different from old_string)",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences of old_string (default: false)",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def _check_write_access(self, path: Path) -> tuple[bool, str | None]:
        """Check if path is allowed for writing."""
        return is_path_allowed(path, self.allowed_write_paths, self.denied_write_paths)

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Perform exact string replacement in a file."""
        file_path = input.get("file_path", "")
        old_string = input.get("old_string", "")
        new_string = input.get("new_string", "")
        replace_all = input.get("replace_all", False)

        if not file_path:
            error_msg = "file_path is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        if not old_string:
            error_msg = "old_string is required"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        if old_string == new_string:
            error_msg = (
                "old_string and new_string must be different (no changes to make)"
            )
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg},
            )

        path = Path(file_path).expanduser()
        if not path.is_absolute() and self.working_dir:
            path = Path(self.working_dir) / path

        allowed, error_msg = self._check_write_access(path)
        if not allowed:
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        if not path.exists():
            error_msg = f"File not found: {file_path}"
            return ToolResult(
                success=False, output=error_msg, error={"message": error_msg}
            )

        try:
            content = path.read_text(encoding="utf-8")

            if old_string not in content:
                error_msg = f"old_string not found in file: {file_path}"
                return ToolResult(
                    success=False,
                    output=error_msg,
                    error={"message": error_msg, "old_string": old_string},
                )

            if not replace_all:
                occurrences = content.count(old_string)
                if occurrences > 1:
                    error_msg = (
                        f"old_string appears {occurrences} times in file."
                        " Either provide more context to make it unique or set replace_all=true"
                    )
                    return ToolResult(
                        success=False,
                        output=error_msg,
                        error={
                            "message": error_msg,
                            "occurrences": occurrences,
                            "old_string": old_string,
                        },
                    )

            if replace_all:
                new_content = content.replace(old_string, new_string)
                replacements_made = content.count(old_string)
            else:
                new_content = content.replace(old_string, new_string, 1)
                replacements_made = 1

            path.write_text(new_content, encoding="utf-8")
            bytes_written = len(new_content.encode("utf-8"))

            if self.client is not None:
                try:
                    await self.client.request(
                        "request.hook_emit",
                        {
                            "event": ARTIFACT_WRITE,
                            "data": {"path": str(path), "bytes": bytes_written},
                        },
                    )
                except Exception:
                    pass

            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "replacements_made": replacements_made,
                    "bytes_written": bytes_written,
                },
            )

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
        except OSError as e:
            error_msg = f"OS error modifying file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": "OSError", "errno": e.errno},
            )
        except Exception as e:
            error_msg = f"Error modifying file: {str(e)}"
            return ToolResult(
                success=False,
                output=error_msg,
                error={"message": error_msg, "type": type(e).__name__},
            )
