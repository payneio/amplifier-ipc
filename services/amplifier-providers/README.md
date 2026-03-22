# amplifier-providers

IPC service exposing AI provider backends to the Amplifier ecosystem.

## Implemented Providers

| Provider | Status | SDK Dependency |
|---|---|---|
| mock | Complete | None |
| anthropic | Complete | anthropic SDK |
| openai | Stub | openai SDK |
| azure_openai | Stub | openai SDK |
| gemini | Stub | google-generativeai SDK |
| ollama | Stub | ollama SDK |
| vllm | Stub | openai SDK |
| github_copilot | Stub | openai SDK |

## Anthropic Provider

A full implementation of the `ProviderBase` contract wrapping the Anthropic Python SDK.

### Configuration

| Parameter | Default | Description |
|---|---|---|
| `api_key` | env `ANTHROPIC_API_KEY` | Anthropic API key |
| `model` | `claude-sonnet-4-20250514` | Model identifier |
| `max_tokens` | `16384` | Maximum tokens in response |
| `temperature` | — | Sampling temperature (optional) |
| `thinking_budget` | — | Extended thinking token budget (optional) |
| `max_retries` | `5` | Maximum retry attempts on transient errors |
| `min_retry_delay` | `1.0` | Minimum delay (seconds) between retries |
| `max_retry_delay` | `60.0` | Maximum delay (seconds) between retries |

### Features

- **Message conversion** — Amplifier `Message` objects ↔ Anthropic API format
- **Tool conversion** — Amplifier tool schemas ↔ Anthropic tool definitions
- **Error translation** — Anthropic SDK exceptions → Amplifier error types
- **Retry with backoff** — Exponential backoff with jitter on transient errors
- **Rate limit tracking** — Respects `retry-after` headers from the API
- **Prompt caching** — Cache-control breakpoint injection for long system prompts
- **Extended thinking** — Budget-aware thinking block support
- **Tool-result repair** — Automatically completes partial tool-call/result pairs

### Dropped from Upstream

| Method | Reason |
|---|---|
| `get_info()` | Not part of the Amplifier provider contract |
| `list_models()` | Model discovery is out of scope for providers service |
| `close()` | Lifecycle managed by the IPC server |
| `mount()` | Transport concern handled at the server layer |

### Streaming

Streaming support was designed but is not implemented yet. The `complete()` method
returns a single aggregated response. Streaming will be added in a future release.

## Installation

```bash
# Anthropic only
pip install amplifier-providers[anthropic]

# All providers
pip install amplifier-providers[all]
```

## Running as IPC Service

```bash
# Entry-point script
amplifier-providers-serve

# Module invocation
python -m amplifier_providers
```
