"""Tests for the JSON-RPC 2.0 errors module."""

from __future__ import annotations

from amplifier_ipc.protocol.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JsonRpcError,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    make_error_response,
)


# ---------------------------------------------------------------------------
# Error code constant tests
# ---------------------------------------------------------------------------


def test_error_code_values():
    """All 5 error code constants must match JSON-RPC 2.0 spec values."""
    assert PARSE_ERROR == -32700
    assert INVALID_REQUEST == -32600
    assert METHOD_NOT_FOUND == -32601
    assert INVALID_PARAMS == -32602
    assert INTERNAL_ERROR == -32603


# ---------------------------------------------------------------------------
# make_error_response tests
# ---------------------------------------------------------------------------


def test_make_error_response_basic():
    """Produces a valid JSON-RPC 2.0 error response with code/message; no data key."""
    response = make_error_response(
        request_id=1, code=INTERNAL_ERROR, message="Something went wrong"
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["error"]["code"] == INTERNAL_ERROR
    assert response["error"]["message"] == "Something went wrong"
    assert "data" not in response["error"]


def test_make_error_response_with_data():
    """Includes 'data' key in error object when data argument is provided."""
    extra = {"detail": "stack trace here"}
    response = make_error_response(
        request_id=42, code=INVALID_PARAMS, message="Bad params", data=extra
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 42
    assert response["error"]["code"] == INVALID_PARAMS
    assert response["error"]["message"] == "Bad params"
    assert response["error"]["data"] == extra


def test_make_error_response_null_id():
    """Works correctly when the request id is None (e.g. parse errors)."""
    response = make_error_response(
        request_id=None, code=PARSE_ERROR, message="Parse error"
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] is None
    assert response["error"]["code"] == PARSE_ERROR
    assert response["error"]["message"] == "Parse error"


# ---------------------------------------------------------------------------
# JsonRpcError tests
# ---------------------------------------------------------------------------


def test_json_rpc_error_is_exception():
    """JsonRpcError is an Exception with code, message, and data attributes; str() returns message."""
    err = JsonRpcError(code=INTERNAL_ERROR, message="Internal error")
    assert isinstance(err, Exception)
    assert err.code == INTERNAL_ERROR
    assert err.message == "Internal error"
    assert err.data is None
    assert str(err) == "Internal error"


def test_json_rpc_error_with_data():
    """JsonRpcError carries optional data attribute when provided."""
    payload = {"hint": "check your input"}
    err = JsonRpcError(code=INVALID_PARAMS, message="Invalid params", data=payload)
    assert err.code == INVALID_PARAMS
    assert err.message == "Invalid params"
    assert err.data == payload


def test_json_rpc_error_to_response():
    """to_response() delegates to make_error_response and returns a valid error response dict."""
    err = JsonRpcError(code=METHOD_NOT_FOUND, message="Method not found", data=None)
    response = err.to_response(request_id=7)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 7
    assert response["error"]["code"] == METHOD_NOT_FOUND
    assert response["error"]["message"] == "Method not found"
    assert "data" not in response["error"]
