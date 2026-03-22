Remember, you should use `uv` for running tests. But, for this stage, using the `amplifier-ipc` CLI directly will probably be more efficient for iterating. Let's get the whole fetch/register/install/run lifecycle going. If we need some delete/unregister/uninstall commands to make it easier to iterate, let's use those as well. They should help you avoid the errors in having stale code or agent definitions hanging around as you iterate.

## Immediate

- I'd like to not use a custom agent definition in amplifier-ipc/definitions/. Instead, let's use the services in amplifier-ipc/services/ as the actual sources. If the agent and behavior definitions there don't work, let's fix them. Specifically, let's get amplifier-ipc/services/amplifier-foundation/agents/amplifier-dev.yaml working through the whole fetch/register/install/run lifecycle. This will probably involve fixing all the included behavior definitions as well, so once you find out something that wasn't set correctly on them, it would probably be better to fix it on all of them quickly instead of iterating your way there.
- Doesn't seem to be bringing in content from foundation bundle. Is it not getting injected into system prompts? Are at-mentions working?
- Modes, skills, routing-matrix services not wired into foundation agent definition

## Next

- Orchestrator doesn't emit stream.thinking or stream.tool_call_start notifications
- discover --install is a placeholder       
- No lazy install on first run
- Behaviors list {alias: url} dict format not parsed (only flat strings)
- 4 stub tools (shadow, mcp, recipes, python_dev)

## Later

- Provider streaming (all providers non-streaming)
- Wildcard * hook events not supported
