"""JSON-RPC 2.0 error codes, helpers, and exception class."""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Standard JSON-RPC 2.0 error codes
# ---------------------------------------------------------------------------

PARSE_ERROR: int = -32700
INVALID_REQUEST: int = -32600
METHOD_NOT_FOUND: int = -32601
INVALID_PARAMS: int = -32602
INTERNAL_ERROR: int = -32603


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_error_response(
    request_id: Any,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response dict.

    Args:
        request_id: The id from the originating request (may be None).
        code: JSON-RPC error code integer.
        message: Human-readable error description.
        data: Optional additional error data; omitted from the response when None.

    Returns:
        A dict conforming to the JSON-RPC 2.0 error response shape.
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


# ---------------------------------------------------------------------------
# Exception class
# ---------------------------------------------------------------------------


class JsonRpcError(Exception):
    """An exception that carries a JSON-RPC 2.0 error payload.

    Attributes:
        code: JSON-RPC error code integer.
        message: Human-readable error description.
        data: Optional additional error data (None if not set).
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_response(self, request_id: Any) -> dict[str, Any]:
        """Produce a JSON-RPC 2.0 error response dict for this error.

        Args:
            request_id: The id from the originating request.

        Returns:
            A dict conforming to the JSON-RPC 2.0 error response shape.
        """
        return make_error_response(
            request_id=request_id,
            code=self.code,
            message=self.message,
            data=self.data,
        )
