"""Message Router — routes orchestrator requests to services.

Routes JSON-RPC requests from the orchestrator to the appropriate service
based on method name.  Supports:

* Tool execution via registry-based service lookup.
* Hook fan-out in priority order, with short-circuit on DENY/ASK_USER and
  data propagation on MODIFY.
* Context manager operations (add_message, get_messages, clear).
* Provider completion with priority-based fallback.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from amplifier_ipc.host.service_index import ServiceIndex
from amplifier_ipc.protocol.errors import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcError

logger = logging.getLogger(__name__)


class Router:
    """Routes orchestrator JSON-RPC requests to the appropriate service.

    Args:
        registry: Service index mapping component names to service keys.
        services: Dict of service_key → service object (must have a ``.client``
            with an async ``request(method, params)`` method).
        context_manager_key: Key in *services* for the context manager service.
        provider_key: Key in *services* for the provider service.
        state: Optional shared state dict (persisted across turns).
        on_provider_notification: Sync callback invoked for each
            ``stream.provider.*`` notification during provider completion.
        spawn_handler: Async callable that handles ``request.session_spawn``
            requests.  Receives the raw params dict; returns a result dict.
        resume_handler: Async callable that handles ``request.session_resume``
            requests.  Receives the raw params dict; returns a result dict.
    """

    def __init__(
        self,
        registry: ServiceIndex,
        services: dict[str, Any],
        context_manager_key: str,
        provider_key: str,
        provider_name: str | None = None,
        state: dict[str, Any] | None = None,
        on_provider_notification: Any | None = None,
        spawn_handler: Callable[..., Coroutine[Any, Any, Any]] | None = None,
        resume_handler: Callable[..., Coroutine[Any, Any, Any]] | None = None,
    ) -> None:
        self._registry = registry
        self._services = services
        self._context_manager_key = context_manager_key
        self._provider_key = provider_key
        self._provider_name = provider_name
        self._state: dict[str, Any] = state if state is not None else {}
        self._on_provider_notification = on_provider_notification
        self._spawn_handler = spawn_handler
        self._resume_handler = resume_handler

    async def route_request(self, method: str, params: Any) -> Any:
        """Route a request to the appropriate service handler.

        Args:
            method: The request method (e.g. ``"request.tool_execute"``).
            params: The request parameters.

        Returns:
            The result from the service.

        Raises:
            JsonRpcError: With ``INVALID_PARAMS`` if a requested tool is unknown,
                or ``METHOD_NOT_FOUND`` if the routing method is unrecognised.
        """
        if method == "request.tool_execute":
            return await self._route_tool_execute(params)

        if method == "request.hook_emit":
            return await self._route_hook_emit(params)

        if method == "request.context_add_message":
            return await self._services[self._context_manager_key].client.request(
                "context.add_message", params
            )

        if method == "request.context_get_messages":
            return await self._services[self._context_manager_key].client.request(
                "context.get_messages", params
            )

        if method == "request.context_clear":
            return await self._services[self._context_manager_key].client.request(
                "context.clear", params
            )

        if method == "request.provider_complete":
            return await self._route_provider_complete(params)

        if method == "request.state_get":
            key: str | None = params.get("key") if isinstance(params, dict) else None
            return {"value": self._state.get(key)}  # type: ignore[arg-type]

        if method == "request.state_set":
            if not isinstance(params, dict) or "key" not in params:
                raise JsonRpcError(
                    code=INVALID_PARAMS,
                    message="state_set requires a 'key' parameter",
                )
            self._state[params["key"]] = params.get("value")
            return {"ok": True}

        if method == "request.session_spawn":
            if self._spawn_handler is None:
                raise JsonRpcError(
                    code=METHOD_NOT_FOUND,
                    message="Sub-session spawning is not configured",
                )
            return await self._spawn_handler(params)

        if method == "request.session_resume":
            if self._resume_handler is None:
                raise JsonRpcError(
                    code=METHOD_NOT_FOUND,
                    message="Sub-session resume is not configured",
                )
            return await self._resume_handler(params)

        raise JsonRpcError(
            code=METHOD_NOT_FOUND,
            message=f"Unknown routing method: {method!r}",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _route_provider_complete(self, params: Any) -> Any:
        """Route a provider completion request with priority-based fallback.

        Attempts the configured primary provider first.  If it raises a
        ``JsonRpcError`` whose code is ``INVALID_PARAMS`` (e.g. missing API
        key, unknown provider name), falls back to other registered providers
        in priority order.

        Transient errors (rate limits, network timeouts) are NOT retried via
        fallback — they are raised to the caller so the orchestrator's own
        retry logic can handle them.
        """
        provider_params: dict[str, Any] = (
            dict(params) if isinstance(params, dict) else {}
        )

        # Build the ordered list of (provider_name, service_key) to attempt.
        primary_name = self._provider_name
        if primary_name and ":" in primary_name:
            primary_name = primary_name.partition(":")[2]

        # Start with the primary provider, then fallback candidates by priority.
        candidates: list[tuple[str, str]] = []
        if primary_name:
            svc_key = self._registry.get_provider_service(primary_name)
            if svc_key:
                candidates.append((primary_name, svc_key))

        for desc in self._registry.get_providers_by_priority():
            name = desc.get("name", "")
            if name == primary_name:
                continue  # already in the list
            svc_key = self._registry.get_provider_service(name)
            if svc_key:
                candidates.append((name, svc_key))

        if not candidates:
            raise JsonRpcError(
                code=INVALID_PARAMS,
                message="No providers registered in any service",
            )

        last_error: Exception | None = None
        for provider_name, service_key in candidates:
            attempt_params = dict(provider_params)
            if "provider" not in attempt_params:
                attempt_params["provider"] = provider_name

            provider_client = self._services[service_key].client
            prev_callback = getattr(provider_client, "on_notification", None)
            try:
                provider_client.on_notification = self._on_provider_notification
                result = await provider_client.request(
                    "provider.complete", attempt_params
                )
                return result
            except JsonRpcError as exc:
                last_error = exc
                # INVALID_PARAMS typically means provider not available (missing
                # API key, unknown name).  Try the next candidate.
                if exc.code == INVALID_PARAMS:
                    logger.warning(
                        "Provider '%s' unavailable (%s), trying next fallback",
                        provider_name,
                        exc.message,
                    )
                    continue
                # Other errors (rate limit, network, server) are not fallback
                # candidates — re-raise for the orchestrator to handle.
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Provider '%s' raised %s, trying next fallback",
                    provider_name,
                    type(exc).__name__,
                )
                continue
            finally:
                provider_client.on_notification = prev_callback

        # All candidates exhausted
        if isinstance(last_error, JsonRpcError):
            raise last_error
        raise JsonRpcError(
            code=INVALID_PARAMS,
            message=f"All providers failed. Last error: {last_error}",
        )

    async def _route_tool_execute(self, params: Any) -> Any:
        """Route a tool execution request to the service that owns the tool.

        Raises:
            JsonRpcError: With ``INVALID_PARAMS`` if the tool is not found in
                the registry.
        """
        tool_name: str | None = (
            params.get("tool_name") if isinstance(params, dict) else None
        )
        service_key = (
            self._registry.get_tool_service(tool_name)
            if tool_name is not None
            else None
        )

        if service_key is None:
            raise JsonRpcError(
                code=INVALID_PARAMS,
                message=f"Unknown tool: {tool_name!r}",
            )

        return await self._services[service_key].client.request("tool.execute", params)

    async def _route_hook_emit(self, params: Any) -> Any:
        """Fan-out a hook event to all registered hook services in priority order.

        Iterates hook entries sorted by ascending priority.  Returns early if
        any hook returns ``DENY`` or ``ASK_USER``.  A ``MODIFY`` response
        replaces the *data* dict for all subsequent hooks.

        Returns:
            The last hook response, or ``{"action": "CONTINUE"}`` if there are
            no hooks registered for the event.
        """
        event: str | None = params.get("event") if isinstance(params, dict) else None
        data: dict[str, Any] = (
            dict(params.get("data", {})) if isinstance(params, dict) else {}
        )

        entries = self._registry.get_hook_services(event) if event is not None else []

        if not entries:
            return {"action": "CONTINUE"}

        last_response: dict[str, Any] = {"action": "CONTINUE"}

        for entry in entries:
            service_key: str = entry["service_key"]
            response = await self._services[service_key].client.request(
                "hook.emit", {"event": event, "data": data}
            )

            action: str = (
                response.get("action", "CONTINUE")
                if isinstance(response, dict)
                else "CONTINUE"
            )

            if action in ("DENY", "ASK_USER"):
                return response

            if action == "MODIFY":
                data = dict(response.get("data", data))

            last_response = response

        return last_response
