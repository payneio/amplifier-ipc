# amplifier-providers

IPC service exposing AI provider backends to the Amplifier ecosystem.

## Providers

| Provider | SDK | Config Key | Env Var | Default Model |
|---|---|---|---|---|
| `mock` | none | — | — | — |
| `anthropic` | `anthropic` | `api_key` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` |
| `openai` | `openai` | `api_key` | `OPENAI_API_KEY` | `gpt-4o` |
| `azure_openai` | `openai` + `azure-identity` | `api_key`, `azure_endpoint`, `api_version` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION` | — (uses deployment name) |
| `gemini` | `google-generativeai` | `api_key` | `GOOGLE_API_KEY` | `gemini-2.0-flash` |
| `ollama` | `ollama` | `host`, `model` | `OLLAMA_HOST` | `llama3.1` |
| `vllm` | `openai` | `api_base`, `model` | `VLLM_API_BASE` | — (requires model config) |
| `github_copilot` | `openai` | `github_token` | `GITHUB_TOKEN` | — (Copilot-managed) |

## Installation

```bash
# Single provider
pip install amplifier-providers[anthropic]
pip install amplifier-providers[openai]
pip install amplifier-providers[azure]
pip install amplifier-providers[gemini]
pip install amplifier-providers[ollama]
pip install amplifier-providers[vllm]
pip install amplifier-providers[copilot]

# All providers
pip install amplifier-providers[all]
```

## Provider Configuration

### mock

No SDK required. Returns canned responses for testing and development.

### anthropic

```python
config = {
    "api_key": "sk-ant-...",          # or env ANTHROPIC_API_KEY
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 16384,
    "temperature": 1.0,               # optional
    "thinking_budget": 10000,         # optional — enables extended thinking
    "max_retries": 5,
    "min_retry_delay": 1.0,
    "max_retry_delay": 60.0,
}
```

**Features:** message conversion, tool conversion, error translation, retry with backoff, rate limit tracking, prompt caching, extended thinking, tool-result repair.

### openai

```python
config = {
    "api_key": "sk-...",              # or env OPENAI_API_KEY
    "model": "gpt-4o",
}
```

### azure_openai

```python
config = {
    "api_key": "...",                 # or env AZURE_OPENAI_API_KEY
    "azure_endpoint": "https://...",  # or env AZURE_OPENAI_ENDPOINT
    "api_version": "2024-02-01",      # or env AZURE_OPENAI_API_VERSION
    "model": "<deployment-name>",     # Azure deployment name
}
```

### gemini

```python
config = {
    "api_key": "...",                 # or env GOOGLE_API_KEY
    "model": "gemini-2.0-flash",
}
```

### ollama

```python
config = {
    "host": "http://localhost:11434", # or env OLLAMA_HOST
    "model": "llama3.1",
}
```

### vllm

```python
config = {
    "api_base": "http://localhost:8000/v1",  # or env VLLM_API_BASE
    "model": "<model-name>",                 # required
}
```

### github_copilot

```python
config = {
    "github_token": "ghp_...",        # or env GITHUB_TOKEN
}
```

## Running as IPC Service

```bash
# Entry-point script
amplifier-providers-serve

# Module invocation
python -m amplifier_providers
```

## Dropped from Upstream

These methods from upstream provider interfaces were not ported because they fall outside the Amplifier provider contract:

| Method | Reason |
|---|---|
| `get_info()` | Not part of the Amplifier provider contract |
| `list_models()` | Model discovery is out of scope for providers service |
| `close()` | Lifecycle managed by the IPC server |
| `mount()` | Transport concern handled at the server layer |
