# Using Providers in Amplifier IPC

Providers are the LLM backends that power Amplifier IPC sessions. This guide
covers how to configure, select, and extend providers.

## Quick Start

Set an API key and start a session:

```bash
# Store your API key securely
amplifier-ipc provider set-key anthropic
# Prompts for key, saves to ~/.amplifier/keys.env

# Set the default provider
amplifier-ipc provider use anthropic

# Optionally pin a specific model
amplifier-ipc provider use anthropic --model claude-sonnet-4-20250514

# Run a session
amplifier-ipc run "Hello, world"
```

That's it. The foundation agent definition ships with `provider: anthropic` as
the default. If your key is set, sessions just work.

## Available Providers

All providers live in the `amplifier-providers` service
(`services/amplifier-providers/`). Eight are shipped:

| Provider | Name | Key Env Var | Notes |
|----------|------|-------------|-------|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Default. Full-featured: retry, rate-limit tracking, tool repair, prompt caching, thinking. |
| OpenAI | `openai` | `OPENAI_API_KEY` | Supports reasoning_effort. |
| Azure OpenAI | `azure_openai` | `AZURE_OPENAI_API_KEY` | Extends OpenAI. Supports Azure AD token fallback. |
| Google Gemini | `gemini` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Thinking budget support. |
| Ollama | `ollama` | `OLLAMA_HOST` (optional) | Local models. No API key required. |
| vLLM | `vllm` | `VLLM_API_KEY` (optional) | Extends OpenAI. Points at a vLLM server. |
| GitHub Copilot | `github_copilot` | `GITHUB_TOKEN` or `GH_TOKEN` | Token exchange flow. Extends OpenAI. |
| Mock | `mock` | (none) | Pattern-matching test mock. |

## How Providers Work

### Architecture Overview

```
CLI (amplifier-ipc)
  │
  │  launch_session()
  ▼
Host
  │  1. Spawns amplifier-providers-serve as a subprocess
  │  2. Sends describe → gets list of provider names
  │  3. Sends configure → passes per-component config
  │  4. Registers provider names in the capability registry
  │
  │  During a session turn:
  │  Orchestrator → request.provider_complete → Router → provider.complete → Provider
  ▼
amplifier-providers-serve (IPC subprocess)
  │  Server receives provider.complete
  │  Selects provider instance by name
  │  Calls provider.complete(ChatRequest) → ChatResponse
  ▼
LLM API (Anthropic, OpenAI, etc.)
```

Providers communicate over **JSON-RPC 2.0 via stdio**. The host and provider
service are separate processes. This gives providers full isolation — a provider
crash won't take down the host.

### The Provider Protocol

Every provider implements this contract:

```python
@provider
class MyProvider:
    name = "my_provider"

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key = config.get("api_key") or os.environ.get("MY_API_KEY")
        self.model = config.get("model", "default-model-name")
        # ...

    async def complete(self, request: ChatRequest) -> ChatResponse:
        # Call the LLM API and return a ChatResponse
        ...
```

Key points:
- **`@provider` decorator** — stamps the class for auto-discovery. No base class required.
- **`name` class attribute** — the string used to select this provider (e.g., `"anthropic"`).
- **`__init__(self, config: dict | None = None)`** — receives config from the host's `configure` call. Falls back to environment variables when config keys are absent.
- **`complete(self, request: ChatRequest) -> ChatResponse`** — the core method. Takes a `ChatRequest` (messages, tools, system prompt, temperature, etc.) and returns a `ChatResponse` (content blocks, tool calls, usage, etc.).

### Discovery

The `Server` class in `amplifier-ipc-protocol` auto-discovers providers at
startup by scanning the `providers/` subdirectory for classes decorated with
`@provider`. No registration code is needed — drop a file in the right directory
and it's found.

## Configuration

Provider configuration flows through multiple layers with clear precedence.

### Layer 1: API Keys (Required)

API keys are stored in `~/.amplifier/keys.env` and loaded into environment
variables at CLI startup.

```bash
# Interactive (recommended — hides input)
amplifier-ipc provider set-key anthropic
# Saves ANTHROPIC_API_KEY="sk-..." to ~/.amplifier/keys.env (chmod 600)

# Or set directly in your shell environment
export ANTHROPIC_API_KEY="sk-ant-..."
```

The `keys.env` file uses a simple `KEY="value"` format. The `KeyManager` loads
these into `os.environ` at startup, skipping any keys that are already set. This
means shell environment variables take precedence over `keys.env`.

**Security note:** Never store raw API keys in `settings.yaml` or definition
files. Always use environment variables or `keys.env`.

### Layer 2: Default Provider Selection

Set which provider to use by default:

```bash
# Set the default provider
amplifier-ipc provider use anthropic

# Set with a specific model
amplifier-ipc provider use openai --model gpt-5.4

# View current configuration
amplifier-ipc provider list
```

This writes to your local settings file (`.amplifier/settings.local.yaml`):

```yaml
provider: anthropic
provider_overrides:
  - provider: anthropic
    model: claude-sonnet-4-20250514
```

### Layer 3: Agent Definition

Agent definition files declare the provider at the agent level:

```yaml
# definitions/foundation-agent.yaml
type: agent
local_ref: foundation
orchestrator: streaming
context_manager: simple
provider: anthropic          # ← provider selection

services:
  - name: amplifier-foundation-serve
    source: ../services/amplifier-foundation
  - name: amplifier-providers-serve
    source: ../services/amplifier-providers
```

The `provider:` field names which provider the orchestrator should use for LLM
calls. The `services:` list must include the service that hosts that provider
(here, `amplifier-providers-serve`).

### Layer 4: Per-Component Config in Definitions

Definition files support a `config:` block for passing settings to specific
components. For providers, this is how you set model, temperature, and other
provider-specific options:

```yaml
# In a behavior or agent definition
config:
  anthropic:
    model: claude-sonnet-4-20250514
    max_tokens: 8192
    temperature: 0.7
```

The host merges this config and sends it to the provider service via the
`configure` JSON-RPC call during startup. The provider's `__init__` receives
it as the `config` dict.

### Layer 5: Settings File Overrides

Three-scope YAML merge (later scopes override earlier ones):

| Scope | File | Precedence |
|-------|------|------------|
| Global | `~/.amplifier/settings.yaml` | Lowest |
| Project | `.amplifier/settings.yaml` | Middle |
| Local | `.amplifier/settings.local.yaml` | Highest |

```yaml
# ~/.amplifier/settings.yaml (global defaults)
provider: anthropic

# .amplifier/settings.yaml (project-level)
provider: openai
provider_overrides:
  - provider: openai
    model: gpt-5.4
```

### Configuration Precedence Summary

When the host resolves what provider to use and how to configure it, the
effective configuration is determined by this precedence (highest wins):

1. **CLI settings** (`provider:` and `provider_overrides:` in settings files)
2. **Agent definition** (`provider:` field, `config:` block)
3. **Behavior defaults** (config in included behaviors)
4. **Provider defaults** (hardcoded in the provider's `__init__`)
5. **Environment variables** (fallback when config keys are absent)

### Config Keys by Provider

Each provider reads specific keys from its `config` dict:

**Anthropic:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | — | `ANTHROPIC_API_KEY` |
| `model` | `claude-sonnet-4-20250514` | — |
| `max_tokens` | `16384` | — |
| `temperature` | (API default) | — |
| `thinking_budget` | (disabled) | — |

**OpenAI:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | — | `OPENAI_API_KEY` |
| `model` | `gpt-4o` | — |
| `max_tokens` | `16384` | — |
| `temperature` | (API default) | — |
| `reasoning_effort` | (none) | — |

**Azure OpenAI:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | — | `AZURE_OPENAI_API_KEY` |
| `azure_endpoint` | — | `AZURE_OPENAI_ENDPOINT` |
| `api_version` | `2024-12-01-preview` | `AZURE_OPENAI_API_VERSION` |
| `model` | (required) | — |

**Gemini:**
| Key | Default | Env Var |
|-----|---------|---------|
| `api_key` | — | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `model` | `gemini-2.0-flash` | — |
| `max_tokens` | `8192` | — |
| `thinking_budget` | (disabled) | — |

**Ollama:**
| Key | Default | Env Var |
|-----|---------|---------|
| `host` | `http://localhost:11434` | `OLLAMA_HOST` |
| `model` | `llama3.2` | — |

**vLLM:**
| Key | Default | Env Var |
|-----|---------|---------|
| `base_url` | — | `VLLM_API_BASE` |
| `api_key` | — | `VLLM_API_KEY` |
| `model` | (required) | — |

**GitHub Copilot:**
| Key | Default | Env Var |
|-----|---------|---------|
| `token` | — | `GITHUB_TOKEN` or `GH_TOKEN` |
| `model` | `gpt-4o` | — |

## Routing Matrix

The routing matrix maps semantic **roles** (like `coding`, `reasoning`, `fast`)
to specific provider/model combinations. This lets sub-agents request the right
kind of model without hardcoding provider names.

### CLI Commands

```bash
# List available matrices
amplifier-ipc routing list

# Show roles in a matrix
amplifier-ipc routing show balanced

# Set the active matrix
amplifier-ipc routing use balanced
```

### Matrix Files

Matrices live in `~/.amplifier/routing/` as YAML files or are shipped as content
in the `amplifier-routing-matrix` service:

```yaml
# ~/.amplifier/routing/balanced.yaml
name: balanced
roles:
  general:
    provider: anthropic
    model: claude-sonnet-4-20250514
    description: Versatile catch-all
  fast:
    provider: anthropic
    model: claude-haiku-3-5
    description: Quick utility tasks
  coding:
    provider: anthropic
    model: claude-sonnet-4-20250514
    description: Code generation and debugging
  reasoning:
    provider: anthropic
    model: claude-opus-4
    description: Deep architectural reasoning
```

### How Routing Works

The routing matrix is implemented as a **hook** (`RoutingHook`) in the
`amplifier-routing-matrix` service. It registers on two events:

- **`session:start`** — logs active matrix info.
- **`provider:request`** — resolves `model_role` to a concrete provider+model
  pair and injects available role information into context.

To include routing in your agent, add the routing behavior:

```yaml
# In your agent definition
behaviors:
  - routing   # from amplifier-routing-matrix service
```

### Using Routing in Definitions

Configure the default matrix in a behavior or agent config block:

```yaml
config:
  routing-hook:
    default_matrix: balanced
```

## Developing a New Provider

### Step 1: Create the Provider File

Add a new file in `services/amplifier-providers/src/amplifier_providers/providers/`:

```python
# services/amplifier-providers/src/amplifier_providers/providers/my_provider.py

from __future__ import annotations

import os
from typing import Any

from amplifier_ipc.protocol import ChatRequest, ChatResponse, provider


@provider
class MyProvider:
    """My custom LLM provider."""

    name = "my_provider"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.api_key = config.get("api_key") or os.environ.get("MY_PROVIDER_API_KEY")
        self.model = config.get("model", "default-model")
        if not self.api_key:
            raise ValueError(
                "MY_PROVIDER_API_KEY not set. Run: "
                "amplifier-ipc provider set-key my_provider"
            )

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        # 1. Convert request.messages to vendor format
        # 2. Call the LLM API
        # 3. Convert response to ChatResponse
        ...
```

### Step 2: Add SDK Dependency

Edit `services/amplifier-providers/pyproject.toml`:

```toml
dependencies = [
    "amplifier-ipc",
    "my-provider-sdk",   # ← add your SDK
    # ... existing deps
]
```

### Step 3: Use It

The `Server` auto-discovers `@provider`-decorated classes. No registration
needed. Set the key and point your definition at it:

```bash
amplifier-ipc provider set-key my_provider
```

```yaml
# In your agent definition
provider: my_provider
```

### Provider Implementation Patterns

Follow these patterns from the existing providers:

1. **Lazy client initialization** — use a `@property` that imports the SDK on
   first access. This avoids import-time failures when the SDK is missing.

2. **Message conversion** — implement `_convert_messages()` to translate
   Amplifier's message format to the vendor's format.

3. **Tool conversion** — implement `_convert_tools_from_request()` to translate
   `ToolSpec` objects to the vendor's function-calling format.

4. **Response conversion** — implement `_convert_to_chat_response()` to produce
   a `ChatResponse` with proper content blocks, tool calls, and usage info.

5. **Error handling** — use retry logic for transient API errors. See
   `AnthropicProvider.retry_with_backoff()` for a reference implementation.

## Provider Metadata

Each provider exposes rich metadata via the `describe` protocol, enabling
tooling to make informed decisions without hardcoded knowledge:

```python
@provider
class MyProvider:
    name = "my_provider"
    display_name = "My Provider"
    env_vars = ["MY_PROVIDER_API_KEY"]
    supported_models = ["model-a", "model-b"]
    capabilities = ["streaming", "tools"]
    config_fields = [
        {"id": "api_key", "field_type": "secret", "required": True,
         "env_var": "MY_PROVIDER_API_KEY", "description": "API key"},
        {"id": "model", "field_type": "text", "default": "model-a",
         "description": "Model name"},
    ]
    priority = 50  # lower = higher priority
```

These class attributes are read at `describe` time (before instantiation) and
returned as `ProviderDescriptor` objects in the describe response. The CLI
`provider configure` wizard, auto-detection, and priority-based fallback all
use this metadata.

## Provider Auto-Detection

When no provider is explicitly configured (neither in settings nor in the agent
definition), the session launcher auto-detects available providers by checking
environment variables:

```bash
# See what's auto-detectable
amplifier-ipc provider detect
```

Detection order: `ANTHROPIC_API_KEY` > `OPENAI_API_KEY` >
`AZURE_OPENAI_API_KEY` (+ endpoint) > `GEMINI_API_KEY` > `GITHUB_TOKEN`.

The first provider with a valid key wins. To override auto-detection, set a
default explicitly:

```bash
amplifier-ipc provider use openai
```

## Provider Fallback Chain

When the primary provider fails with a configuration error (missing API key,
unknown model), the router automatically tries other registered providers in
**priority order** (lower priority number = tried first):

| Priority | Provider |
|----------|----------|
| 10 | Anthropic |
| 20 | OpenAI |
| 25 | Azure OpenAI |
| 30 | Gemini |
| 40 | GitHub Copilot |
| 50 | Ollama |
| 60 | vLLM |
| 999 | Mock |

Only configuration errors trigger fallback. Transient errors (rate limits,
network timeouts) are re-raised to the orchestrator's own retry logic.

## Interactive Configuration

For guided setup of all provider settings (not just API keys):

```bash
amplifier-ipc provider configure anthropic
```

This walks through each field:
- **Secret fields** (API keys) — prompted securely, saved to `keys.env`
- **Text fields** (model, endpoint) — prompted with defaults shown
- **Number fields** (max_tokens, temperature) — prompted with defaults

After configuration, offers to set the provider as the default.

## Troubleshooting

### "Provider 'X' not found in registry"

The host couldn't find the named provider in any running service.

- Verify the provider service is listed in your agent definition's `services:`.
- Check that the service starts without errors: run the service command directly
  (e.g., `amplifier-providers-serve`) and look for import errors.
- Verify the provider's `name` attribute matches what you're referencing.

### API key not working

- Run `amplifier-ipc provider set-key <provider>` to re-enter the key.
- Check that `~/.amplifier/keys.env` exists and has the correct `KEY="value"`.
- Verify the env var name matches what the provider expects (see the config
  keys table above).
- Shell environment variables take precedence over `keys.env`.

### Provider crashes during a session

Since providers run as separate IPC processes, a crash in the provider service
will surface as a JSON-RPC error in the host. Check the provider service's
stderr output for the actual error. Common causes:

- Missing or expired API key
- Rate limiting (Anthropic provider has built-in rate-limit tracking)
- Model name mismatch
- Network connectivity issues

### Using a local development provider

For development, use service overrides in settings to point at your local
checkout:

```yaml
# ~/.amplifier/settings.yaml
amplifier_ipc:
  service_overrides:
    amplifier-providers-serve:
      command: ["python", "-m", "amplifier_providers.server"]
      working_dir: ~/dev/amplifier-providers
```

### Provider fallback kicked in unexpectedly

The router logs fallback attempts at WARNING level. Check logs for:

```
Provider 'X' unavailable (missing API key), trying next fallback
```

This means the primary provider's API key isn't set. Either set the key or
change your default provider.

## Provider Cleanup

Providers that hold HTTP connections implement an async `close()` method.
The server calls `close()` on all provider instances during `shutdown`.
For providers extending `OpenAIProvider` (Azure, vLLM, Copilot), `close()`
delegates to the parent.

For custom providers, implement `close()` if your provider holds persistent
connections:

```python
async def close(self) -> None:
    if self._client is not None:
        await self._client.aclose()
        self._client = None
```

## CLI Command Reference

| Command | Description |
|---------|-------------|
| `provider list` | Show default provider and any overrides |
| `provider use <name> [--model M]` | Set default provider (and model) |
| `provider set-key <name>` | Securely set API key |
| `provider configure <name>` | Interactive guided configuration |
| `provider detect` | Auto-detect providers from env vars |
| `routing list` | List available routing matrices |
| `routing show <name>` | Display roles in a matrix |
| `routing use <name>` | Set active matrix |
