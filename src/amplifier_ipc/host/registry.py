"""Capability registry — routing table built from service describe responses."""

from __future__ import annotations


class CapabilityRegistry:
    """Maps capability names to the services that provide them.

    Built by calling :meth:`register` once per service with the result of that
    service's ``describe`` response.  The registry can then be queried to
    determine which service should handle a given tool call, hook event,
    orchestrator request, etc.
    """

    def __init__(self) -> None:
        self._tool_to_service: dict[str, str] = {}
        self._hook_entries: list[dict] = []
        self._orchestrator_to_service: dict[str, str] = {}
        self._context_manager_to_service: dict[str, str] = {}
        self._provider_to_service: dict[str, str] = {}
        self._content_by_service: dict[str, list[str]] = {}
        self._all_tool_specs: list[dict] = []
        self._all_hook_descriptors: list[dict] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, service_key: str, describe_result: dict) -> None:
        """Index all capabilities advertised by *service_key*.

        Args:
            service_key: Stable identifier for the service (e.g. ``"foundation"``).
            describe_result: The dict returned by that service's ``describe``
                endpoint, containing ``tools``, ``hooks``, ``orchestrators``,
                ``context_managers``, ``providers``, and ``content`` lists.
        """
        # Tools
        # Policy: if two services register the same name, the last registration wins.
        for tool_spec in describe_result.get("tools", []):
            try:
                name = tool_spec["name"]
            except KeyError as exc:
                raise KeyError(
                    f"Tool descriptor from service '{service_key}' is missing 'name' key: {tool_spec!r}"
                ) from exc
            self._tool_to_service[name] = service_key
            # Replace any existing spec with the same name (last-wins dedup).
            self._all_tool_specs = [
                s for s in self._all_tool_specs if s.get("name") != name
            ]
            self._all_tool_specs.append(tool_spec)

        # Hooks — one entry per (service, hook_name, event, priority) tuple
        # Policy: duplicate hook names across services are all retained (hooks fan-out).
        #
        # Protocol supports two hook-event formats:
        #   - "event": "tool:pre"          (singular string — legacy/unit-test format)
        #   - "events": ["tool:pre", ...]  (plural list — real service format)
        for hook_descriptor in describe_result.get("hooks", []):
            try:
                hook_name = hook_descriptor["name"]
                priority = hook_descriptor["priority"]
            except KeyError as exc:
                raise KeyError(
                    f"Hook descriptor from service '{service_key}' is missing key {exc}: {hook_descriptor!r}"
                ) from exc

            # Resolve event(s): accept both plural list and singular string.
            if "events" in hook_descriptor:
                events: list[str] = list(hook_descriptor["events"])
            elif "event" in hook_descriptor:
                events = [hook_descriptor["event"]]
            else:
                raise KeyError(
                    f"Hook descriptor from service '{service_key}' is missing 'event' or 'events' key: {hook_descriptor!r}"
                )

            for event in events:
                self._hook_entries.append(
                    {
                        "service_key": service_key,
                        "hook_name": hook_name,
                        "event": event,
                        "priority": priority,
                    }
                )
            self._all_hook_descriptors.append(hook_descriptor)

        # Orchestrators
        # Policy: last registration wins on name collision.
        # Components are registered under both the bare name ("streaming") and
        # the qualified name ("foundation:streaming") per the spec's
        # <service>:<name> convention.
        for orch in describe_result.get("orchestrators", []):
            try:
                name = orch["name"]
            except KeyError as exc:
                raise KeyError(
                    f"Orchestrator descriptor from service '{service_key}' is missing 'name' key: {orch!r}"
                ) from exc
            self._orchestrator_to_service[name] = service_key
            self._orchestrator_to_service[f"{service_key}:{name}"] = service_key

        # Context managers
        # Policy: last registration wins on name collision.
        for ctx_mgr in describe_result.get("context_managers", []):
            try:
                name = ctx_mgr["name"]
            except KeyError as exc:
                raise KeyError(
                    f"Context manager descriptor from service '{service_key}' is missing 'name' key: {ctx_mgr!r}"
                ) from exc
            self._context_manager_to_service[name] = service_key
            self._context_manager_to_service[f"{service_key}:{name}"] = service_key

        # Providers
        # Policy: last registration wins on name collision.
        for provider in describe_result.get("providers", []):
            try:
                name = provider["name"]
            except KeyError as exc:
                raise KeyError(
                    f"Provider descriptor from service '{service_key}' is missing 'name' key: {provider!r}"
                ) from exc
            self._provider_to_service[name] = service_key
            self._provider_to_service[f"{service_key}:{name}"] = service_key

        # Content paths
        content_paths = describe_result.get("content", [])
        if content_paths:
            self._content_by_service[service_key] = list(content_paths)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_tool_service(self, tool_name: str) -> str | None:
        """Return the service key that provides *tool_name*, or ``None``."""
        return self._tool_to_service.get(tool_name)

    def get_hook_services(self, event: str) -> list[dict]:
        """Return all hook entries for *event*, sorted by priority ascending.

        Each entry is a dict with keys: ``service_key``, ``hook_name``,
        ``event``, ``priority``.
        """
        matching = [e for e in self._hook_entries if e["event"] == event]
        return sorted(matching, key=lambda e: e["priority"])

    def get_orchestrator_service(self, name: str) -> str | None:
        """Return the service key that provides orchestrator *name*, or ``None``."""
        return self._orchestrator_to_service.get(name)

    def get_context_manager_service(self, name: str) -> str | None:
        """Return the service key that provides context manager *name*, or ``None``."""
        return self._context_manager_to_service.get(name)

    def get_provider_service(self, name: str) -> str | None:
        """Return the service key that provides provider *name*, or ``None``."""
        return self._provider_to_service.get(name)

    def get_content_services(self) -> dict[str, list[str]]:
        """Return a mapping of service_key → list of content paths."""
        return dict(self._content_by_service)

    def get_all_tool_specs(self) -> list[dict]:
        """Return all tool specs accumulated across all registered services."""
        return list(self._all_tool_specs)

    def get_all_hook_descriptors(self) -> list[dict]:
        """Return all hook descriptors accumulated across all registered services."""
        return list(self._all_hook_descriptors)
