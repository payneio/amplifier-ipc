## Amplifier IPC

An implementation of Amplifier where every component (orchestrator, tools, hooks, providers, context manager) runs as its own subprocess, communicating with a central host over JSON-RPC 2.0 via stdio. This gives process-level isolation, per-service dependency management, and a path to multi-language services.

For architecture details, see `docs/specs/amplifier-ipc-spec.md`.

## Quick Start

### Install

```bash
uv tool install git+https://github.com/payneio/amplifier-ipc
```

### Set Up an Agent

Discover, register, and install services from a local path or URL:

```bash
amplifier-ipc discover ./services/amplifier-foundation --register --install
```

Or register a single definition:

```bash
amplifier-ipc register ./definitions/foundation-agent.yaml --install
```

### Run

```bash
# Interactive REPL
amplifier-ipc run --agent foundation

# Single-shot
amplifier-ipc run --agent foundation "What files are in this directory?"
```

## Session Management

Sessions persist across turns. Resume a previous session or list past ones:

```bash
amplifier-ipc session list
amplifier-ipc session resume <session-id>
```

## Service Management

```bash
amplifier-ipc install <ref>        # Create venv, install deps (also runs on first use)
amplifier-ipc update <ref>         # Re-fetch a remote definition and reinstall if changed
amplifier-ipc unregister <ref>     # Remove a registered definition
amplifier-ipc uninstall <ref>      # Remove installed environment
```

## Configuration

Settings are merged from three scopes (later overrides earlier):

1. Global: `~/.amplifier/settings.yaml`
2. Project: `.amplifier/settings.yaml`
3. Local: `.amplifier/settings.local.yaml`

```bash
amplifier-ipc provider             # Configure LLM provider
amplifier-ipc routing              # Configure model routing
amplifier-ipc reset                # Reset settings
```

## Project Structure

```
src/amplifier_ipc/
  protocol/          # JSON-RPC 2.0 library: models, framing, server, client, decorators
  host/              # Central bus: service spawning, message routing, sessions, persistence
  cli/               # Commands, REPL, settings, streaming display

services/
  amplifier-foundation/       # Orchestrator, context manager, tools, hooks
  amplifier-providers/        # LLM providers (anthropic, openai, azure, gemini, ollama, ...)
  amplifier-modes/            # Runtime mode overlays (hook + tool)
  amplifier-skills/           # Skills discovery and loading (tool)
  amplifier-routing-matrix/   # Model routing (hook)
  amplifier-core/             # Content only (context files)
  amplifier-amplifier/        # Content only
  amplifier-browser-tester/   # Content only
  amplifier-design-intelligence/  # Content only
  amplifier-filesystem/       # Content only
  amplifier-recipes/          # Content only
  amplifier-superpowers/      # Content only

definitions/                  # Agent and behavior definition YAML
docs/specs/                   # Authoritative spec
```

## Writing Services

A service is a Python package that exposes components via decorators:

```python
from amplifier_ipc.protocol import tool, hook, provider, orchestrator, context_manager

@tool
class MyTool:
    name = "my_tool"
    description = "Does something useful"

    async def execute(self, input: dict) -> dict:
        return {"result": "done"}
```

The host discovers components automatically -- no YAML registration of individual tools or hooks. Just decorate your classes and the `describe` call finds them.

Run your service with the protocol's built-in server:

```python
from amplifier_ipc.protocol import Server

server = Server("my_service")
server.run()
```
