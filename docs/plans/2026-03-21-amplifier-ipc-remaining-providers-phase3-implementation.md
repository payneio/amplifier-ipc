# Remaining 6 Providers + End-to-End Smoke Test — Phase 3 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Replace the 6 remaining provider stubs (OpenAI, Gemini, Azure OpenAI, Ollama, vLLM, GitHub Copilot) with fully functional providers faithfully ported from upstream, create a foundation agent definition YAML, and prove the full stack works end-to-end.

**Architecture:** Each provider converts between Amplifier's data models (`ChatRequest`, `ChatResponse`, `Message`, `ToolCall`, `TextBlock`, `ThinkingBlock`, `ToolCallBlock`, `Usage`) and its upstream SDK's format. All 6 follow the same porting recipe proven by the Anthropic provider in Phase 2: swap imports (`amplifier_core.*` → `amplifier_ipc_protocol.*`), drop v1 lifecycle (`mount()`, `get_info()`, `list_models()`, `close()`), add `@provider` decorator, change `__init__` to take `config: dict | None`. No refactoring — faithful ports.

**Tech Stack:** Python 3.11+, `openai` SDK, `google-generativeai` SDK, `azure-identity`, `ollama` SDK, `amplifier-ipc-protocol` (Pydantic v2 models, `@provider` decorator), `pytest` + `pytest-asyncio`

---

## Verified Paths and Conventions

These paths and patterns were verified by reading the codebase:

| Item | Path |
|---|---|
| Provider stubs to replace | `services/amplifier-providers/src/amplifier_providers/providers/{openai,gemini,azure_openai,ollama,vllm,github_copilot}_provider.py` |
| Anthropic provider (reference) | `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py` |
| Mock provider (pattern reference) | `services/amplifier-providers/src/amplifier_providers/providers/mock.py` |
| Protocol models | `amplifier-ipc-protocol/src/amplifier_ipc_protocol/models.py` |
| Protocol `__init__.py` (public API) | `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py` |
| Provider pyproject.toml | `services/amplifier-providers/pyproject.toml` |
| Test directory | `services/amplifier-providers/tests/` |
| Existing tests | `tests/test_scaffolding.py`, `tests/test_describe.py`, `tests/test_mock_provider.py` |
| Host package | `amplifier-ipc-host/src/amplifier_ipc_host/` |
| Host config | `amplifier-ipc-host/src/amplifier_ipc_host/config.py` — `SessionConfig`, `HostSettings` |
| Host main class | `amplifier-ipc-host/src/amplifier_ipc_host/host.py` — `Host.run()` yields `HostEvent` |
| CLI session launcher | `amplifier-ipc-cli/src/amplifier_ipc_cli/session_launcher.py` — `launch_session()`, `build_session_config()` |
| CLI registry | `amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` |
| CLI definitions | `amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py` |
| Foundation sessions | `services/amplifier-foundation/sessions/` — `default.yaml`, `minimal.yaml`, `with-anthropic.yaml` |
| Host tests | `amplifier-ipc-host/tests/` — includes `test_host.py`, `test_integration.py` |

**Import pattern** (from mock/anthropic providers):
```python
from amplifier_ipc_protocol import ChatRequest, ChatResponse, TextBlock, ToolCall, Usage, provider
from amplifier_ipc_protocol import Message, ThinkingBlock, ToolCallBlock, ToolSpec
```

**Provider class pattern** (from mock provider):
```python
@provider
class MockProvider:
    name = "mock"
    def __init__(self, config: dict | None = None) -> None: ...
    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse: ...
```

**Test pattern** (from `test_mock_provider.py`):
```python
from amplifier_ipc_protocol import ChatRequest, ChatResponse, Message
from amplifier_providers.providers.mock import MockProvider

async def test_mock_provider_complete_returns_chat_response() -> None:
    provider = MockProvider()
    request = ChatRequest(messages=[Message(role="user", content="Hello")])
    response = await provider.complete(request)
    assert isinstance(response, ChatResponse)
```

**Existing test that must be updated** (`test_describe.py` lines 88–116):
`test_stub_providers_raise_not_implemented` asserts that all 7 non-mock providers raise `NotImplementedError`. After Phase 2 (Anthropic) and Phase 3 (all others), this test must be deleted entirely — no providers will be stubs anymore.

**Session config pattern** (from `amplifier-ipc-host/src/amplifier_ipc_host/config.py`):
```python
@dataclass
class SessionConfig:
    services: list[str]
    orchestrator: str
    context_manager: str
    provider: str
    component_config: dict[str, dict[str, Any]] = field(default_factory=dict)
```

---

## Scope Boundaries

**Phase 3 INCLUDES:**
- OpenAI, Gemini, Azure OpenAI, Ollama, vLLM, GitHub Copilot provider implementations (all faithful ports from upstream)
- Unit tests for all conversion functions per provider (mocked SDK clients)
- Update `test_describe.py` to remove `test_stub_providers_raise_not_implemented`
- Update README.md with configuration docs for all 8 providers
- Foundation agent definition YAML for use with `amplifier-ipc run --agent foundation`
- End-to-end smoke test with mock provider (automated, no API key)
- End-to-end smoke test with real Anthropic (manual, API key gated)

**Phase 3 DOES NOT INCLUDE:**
- Provider streaming implementation in providers (protocol designed but providers use non-streaming `complete()` for now)
- Fork at turn N
- Hot-reload
- Networked services

---

## Porting Recipe (Same for All 6 Providers)

Each provider follows the identical porting recipe proven in Phase 2's Anthropic port:

1. **Read upstream source** — understand `__init__`, `_convert_messages()`, `_convert_tools_from_request()`, `_convert_to_chat_response()`, `complete()`, error handling
2. **Swap imports** — `amplifier_core.*` → `amplifier_ipc_protocol.*`
3. **Drop v1 lifecycle** — remove `mount()`, `__amplifier_module_type__`, coordinator references
4. **Add `@provider` decorator** — same pattern as mock/anthropic
5. **Change `__init__`** — takes `config: dict | None`, reads API key from config or env var
6. **Drop unused methods** — `get_info()`, `list_models()`, `close()`
7. **Fix field name differences** — inline adjustments for IPC protocol models
8. **Keep all conversion/error/retry logic** — faithful port, no refactoring

**Important:** Azure OpenAI, vLLM, and GitHub Copilot are OpenAI-compatible. If upstream shares code with the OpenAI provider (common base, shared utilities), preserve that relationship in the IPC port.

---

### Task 1: OpenAI Provider

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/openai_provider.py`
- Create: `services/amplifier-providers/tests/test_openai_provider.py`

The OpenAI provider is the most complex after Anthropic. It uses the OpenAI Responses API (not Chat Completions). Key features from upstream:
- Response continuation logic (incomplete responses get continued automatically)
- Native tool support (OpenAI tools format)
- Reasoning blocks / reasoning effort parameter
- Model capability lookup (per-model feature flags)

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_openai_provider.py`:

```python
"""Tests for OpenAIProvider conversion logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolSpec,
    Usage,
)


class TestOpenAIConvertMessages:
    """Tests for _convert_messages: Amplifier Message list → OpenAI API format."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config={"api_key": "test-key"})

    def test_simple_user_message(self) -> None:
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_user_assistant_alternation(self) -> None:
        p = self._make_provider()
        messages = [
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello!"),
            Message(role="user", content="How are you?"),
        ]
        result = p._convert_messages(messages)
        assert len(result) == 3
        assert result[1]["role"] == "assistant"

    def test_system_message_role_preserved(self) -> None:
        """OpenAI supports system messages directly (unlike Anthropic)."""
        p = self._make_provider()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = p._convert_messages(messages)
        assert result[0]["role"] in ("system", "developer")

    def test_tool_result_message(self) -> None:
        p = self._make_provider()
        messages = [
            Message(role="tool", content="file contents", tool_call_id="tc_1", name="read_file"),
        ]
        result = p._convert_messages(messages)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc_1"

    def test_assistant_with_tool_calls(self) -> None:
        p = self._make_provider()
        messages = [
            Message(
                role="assistant",
                content=[
                    TextBlock(text="I'll read that."),
                    ToolCallBlock(id="tc_1", name="read_file", input={"path": "x.txt"}),
                ],
            ),
        ]
        result = p._convert_messages(messages)
        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert "tool_calls" in msg or isinstance(msg.get("content"), list)


class TestOpenAIConvertTools:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config={"api_key": "test-key"})

    def test_single_tool(self) -> None:
        p = self._make_provider()
        tools = [
            ToolSpec(
                name="bash",
                description="Run shell commands",
                parameters={"type": "object", "properties": {"command": {"type": "string"}}},
            )
        ]
        result = p._convert_tools_from_request(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "bash"

    def test_empty_tools(self) -> None:
        p = self._make_provider()
        result = p._convert_tools_from_request([])
        assert result == []


class TestOpenAIConvertResponse:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config={"api_key": "test-key"})

    def _make_openai_response(
        self,
        text: str = "Hello",
        *,
        tool_calls: list[dict] | None = None,
        input_tokens: int = 50,
        output_tokens: int = 25,
    ) -> MagicMock:
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = text
        mock_message.role = "assistant"
        mock_message.tool_calls = None

        if tool_calls:
            tc_mocks = []
            for tc in tool_calls:
                tc_mock = MagicMock()
                tc_mock.id = tc["id"]
                tc_mock.type = "function"
                tc_mock.function.name = tc["name"]
                tc_mock.function.arguments = '{"path": "test.txt"}'
                tc_mocks.append(tc_mock)
            mock_message.tool_calls = tc_mocks

        mock_choice.message = mock_message
        mock_choice.finish_reason = "tool_calls" if tool_calls else "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = input_tokens
        mock_usage.completion_tokens = output_tokens
        mock_usage.total_tokens = input_tokens + output_tokens

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"
        return mock_response

    def test_text_response(self) -> None:
        p = self._make_provider()
        response = self._make_openai_response("Hello world")
        result = p._convert_to_chat_response(response)
        assert isinstance(result, ChatResponse)
        assert result.content is not None

    def test_tool_call_response(self) -> None:
        p = self._make_provider()
        response = self._make_openai_response(
            "I'll read that.",
            tool_calls=[{"id": "call_123", "name": "read_file"}],
        )
        result = p._convert_to_chat_response(response)
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"

    def test_usage_extraction(self) -> None:
        p = self._make_provider()
        response = self._make_openai_response("hi", input_tokens=200, output_tokens=100)
        result = p._convert_to_chat_response(response)
        assert result.usage is not None
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 100


class TestOpenAIComplete:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(config={"api_key": "test-key"})

    async def test_complete_returns_chat_response(self) -> None:
        p = self._make_provider()

        mock_message = MagicMock()
        mock_message.content = "Hello from GPT!"
        mock_message.role = "assistant"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 25
        mock_usage.total_tokens = 75

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(
            messages=[Message(role="user", content="Hello")],
            system="You are helpful.",
        )
        response = await p.complete(request)
        assert isinstance(response, ChatResponse)
        assert response.content is not None
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_openai_provider.py -v
```

Expected: FAIL — `OpenAIProvider.__init__` doesn't accept config, `_convert_messages` doesn't exist.

**Step 3: Implement the OpenAI provider**

Replace the contents of `services/amplifier-providers/src/amplifier_providers/providers/openai_provider.py` with a faithful port from upstream. The implementation must include:

- `__init__(self, config: dict | None = None)` — reads `api_key` from config or `OPENAI_API_KEY` env var, sets default model to `gpt-4o`, lazy client init
- `_convert_messages(self, messages)` — Amplifier Message list → OpenAI Chat Completions format. OpenAI supports system messages directly. Tool calls use `function` type. Tool results use `role="tool"` with `tool_call_id`.
- `_convert_tools_from_request(self, tools)` — ToolSpec → `{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}`
- `_convert_to_chat_response(self, response)` — OpenAI response → ChatResponse with TextBlock/ToolCallBlock/Usage
- `complete(self, request, **kwargs)` — builds params, handles system message, calls `client.chat.completions.create()`, converts response. Port error handling and retry logic from upstream.
- Error translation: map `openai.RateLimitError`, `openai.AuthenticationError`, `openai.BadRequestError` → `ProviderError` (reuse from anthropic_provider or extract to shared module)
- Reasoning effort support (`reasoning_effort` param on ChatRequest)

Port the `_response_handling` logic (continuation for incomplete responses) and `_capabilities` lookup (per-model feature flags) from upstream if they exist as separate upstream files. If they're inline in the provider, keep them inline.

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_openai_provider.py -v
```

Expected: All tests PASS.

**Step 5: Run all existing tests for regression**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/ -v
```

Expected: All existing tests PASS. `test_stub_providers_raise_not_implemented` may need adjustment (OpenAI no longer raises `NotImplementedError`).

**Step 6: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/openai_provider.py services/amplifier-providers/tests/test_openai_provider.py && git commit -m "feat(openai): port OpenAI provider from upstream with Responses API support"
```

---

### Task 2: Gemini Provider

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/gemini_provider.py`
- Create: `services/amplifier-providers/tests/test_gemini_provider.py`

The Gemini provider uses the `google-generativeai` SDK (imported as `google.generativeai` or `google.genai`). Key differences from OpenAI/Anthropic:
- **Synthetic tool call IDs** — Gemini API does not return tool call IDs; the provider must generate them (e.g., `gemini_call_{uuid}`)
- **`thinking_budget` parameter** — Gemini supports a thinking budget for reasoning
- **Image support** — Gemini supports inline image content
- **Different message format** — Gemini uses `Content` objects with `parts`, not `messages` with `content`

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_gemini_provider.py`:

```python
"""Tests for GeminiProvider conversion logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    TextBlock,
    ToolCall,
    ToolCallBlock,
    ToolSpec,
    Usage,
)


class TestGeminiConvertMessages:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.gemini_provider import GeminiProvider
        return GeminiProvider(config={"api_key": "test-key"})

    def test_simple_user_message(self) -> None:
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) >= 1
        assert result[0]["role"] == "user"

    def test_system_message_extracted(self) -> None:
        """System messages should be extracted for Gemini's system_instruction param."""
        p = self._make_provider()
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="Hello"),
        ]
        result = p._convert_messages(messages)
        # System messages should be excluded from the conversation messages
        for msg in result:
            assert msg["role"] != "system"

    def test_tool_result_message(self) -> None:
        p = self._make_provider()
        messages = [
            Message(role="tool", content="file contents", tool_call_id="tc_1", name="read_file"),
        ]
        result = p._convert_messages(messages)
        assert len(result) >= 1
        # Gemini uses "function" role for tool responses


class TestGeminiConvertTools:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.gemini_provider import GeminiProvider
        return GeminiProvider(config={"api_key": "test-key"})

    def test_single_tool(self) -> None:
        p = self._make_provider()
        tools = [
            ToolSpec(
                name="bash",
                description="Run commands",
                parameters={"type": "object", "properties": {"command": {"type": "string"}}},
            )
        ]
        result = p._convert_tools_from_request(tools)
        assert len(result) >= 1

    def test_empty_tools(self) -> None:
        p = self._make_provider()
        result = p._convert_tools_from_request([])
        assert result == []


class TestGeminiSyntheticToolCallIds:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.gemini_provider import GeminiProvider
        return GeminiProvider(config={"api_key": "test-key"})

    def test_generates_synthetic_ids(self) -> None:
        """Gemini provider must generate synthetic tool call IDs since the API doesn't provide them."""
        p = self._make_provider()
        # Build a mock Gemini response with a function_call but no ID
        mock_response = self._make_gemini_response_with_function_call("read_file", {"path": "x.txt"})
        result = p._convert_to_chat_response(mock_response)
        assert result.tool_calls is not None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id.startswith("gemini_call_")

    def _make_gemini_response_with_function_call(self, name: str, args: dict) -> MagicMock:
        mock_part = MagicMock()
        mock_part.text = None
        mock_part.function_call = MagicMock()
        mock_part.function_call.name = name
        mock_part.function_call.args = args
        mock_part.thought = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_candidate.finish_reason = "STOP"

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 50
        mock_response.usage_metadata.candidates_token_count = 25
        mock_response.usage_metadata.total_token_count = 75
        return mock_response


class TestGeminiComplete:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.gemini_provider import GeminiProvider
        return GeminiProvider(config={"api_key": "test-key"})

    async def test_complete_returns_chat_response(self) -> None:
        p = self._make_provider()

        mock_part = MagicMock()
        mock_part.text = "Hello from Gemini!"
        mock_part.function_call = None
        mock_part.thought = None

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_candidate.finish_reason = "STOP"

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 50
        mock_response.usage_metadata.candidates_token_count = 25
        mock_response.usage_metadata.total_token_count = 75

        mock_model = AsyncMock()
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)
        p._model = mock_model

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        response = await p.complete(request)
        assert isinstance(response, ChatResponse)
        assert response.content is not None
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_gemini_provider.py -v
```

Expected: FAIL — stub doesn't have the expected methods.

**Step 3: Implement the Gemini provider**

Replace `services/amplifier-providers/src/amplifier_providers/providers/gemini_provider.py` with a faithful port from upstream. The implementation must include:

- `__init__(self, config: dict | None = None)` — reads `api_key` from config or `GOOGLE_API_KEY` env var, lazy model init via `google.generativeai`
- `_convert_messages(self, messages)` — Amplifier Message → Gemini Content/Part format. System messages extracted separately for `system_instruction`. User messages → `role="user"`, assistant → `role="model"`, tool results → function response parts
- `_convert_tools_from_request(self, tools)` — ToolSpec → Gemini FunctionDeclaration format
- `_convert_to_chat_response(self, response)` — Gemini response → ChatResponse. **Must generate synthetic tool call IDs** (`gemini_call_{uuid}`) since Gemini API doesn't provide them
- `complete(self, request, **kwargs)` — builds params, handles `thinking_budget` if set, calls `model.generate_content_async()`, converts response
- Error handling for Gemini-specific exceptions

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_gemini_provider.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/gemini_provider.py services/amplifier-providers/tests/test_gemini_provider.py && git commit -m "feat(gemini): port Gemini provider with synthetic tool call IDs and thinking_budget"
```

---

### Task 3: Azure OpenAI Provider

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/azure_openai_provider.py`
- Create: `services/amplifier-providers/tests/test_azure_openai_provider.py`

Azure OpenAI is OpenAI-compatible with Azure-specific authentication. The upstream may share significant code with the OpenAI provider. **Preserve that relationship** — if upstream uses a shared base or imports from the OpenAI provider, keep that pattern.

Key differences from standard OpenAI:
- Authentication via `azure-identity` (Azure AD tokens) OR API key
- Azure-specific endpoint URL format: `https://{resource}.openai.azure.com/`
- Deployment name instead of model name
- May use `AzureOpenAI` client class from the `openai` SDK

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_azure_openai_provider.py`:

```python
"""Tests for AzureOpenAIProvider."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    ToolSpec,
    Usage,
)


class TestAzureOpenAIInit:
    def test_init_with_api_key(self) -> None:
        from amplifier_providers.providers.azure_openai_provider import AzureOpenAIProvider
        p = AzureOpenAIProvider(config={
            "api_key": "test-key",
            "azure_endpoint": "https://test.openai.azure.com/",
            "api_version": "2024-02-15-preview",
        })
        assert p.name == "azure_openai"

    def test_init_without_config(self) -> None:
        from amplifier_providers.providers.azure_openai_provider import AzureOpenAIProvider
        p = AzureOpenAIProvider()
        assert p.name == "azure_openai"


class TestAzureOpenAIConvertMessages:
    """Azure OpenAI should reuse OpenAI message conversion (same API format)."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.azure_openai_provider import AzureOpenAIProvider
        return AzureOpenAIProvider(config={
            "api_key": "test-key",
            "azure_endpoint": "https://test.openai.azure.com/",
        })

    def test_simple_user_message(self) -> None:
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestAzureOpenAIComplete:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.azure_openai_provider import AzureOpenAIProvider
        return AzureOpenAIProvider(config={
            "api_key": "test-key",
            "azure_endpoint": "https://test.openai.azure.com/",
        })

    async def test_complete_returns_chat_response(self) -> None:
        p = self._make_provider()

        mock_message = MagicMock()
        mock_message.content = "Hello from Azure!"
        mock_message.role = "assistant"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 25
        mock_usage.total_tokens = 75

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        response = await p.complete(request)
        assert isinstance(response, ChatResponse)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_azure_openai_provider.py -v
```

**Step 3: Implement the Azure OpenAI provider**

Replace `services/amplifier-providers/src/amplifier_providers/providers/azure_openai_provider.py`. The implementation must:

- `__init__(self, config: dict | None = None)` — reads `api_key` from config or `AZURE_OPENAI_API_KEY` env var, `azure_endpoint` from config or `AZURE_OPENAI_ENDPOINT`, `api_version` from config or `AZURE_OPENAI_API_VERSION`
- **Reuse OpenAI conversion methods** — if upstream shares code with OpenAI provider, import from `openai_provider.py` or use inheritance. The message format, tool format, and response format are identical to OpenAI.
- `complete(self, request, **kwargs)` — uses `openai.AsyncAzureOpenAI` client instead of `openai.AsyncOpenAI`
- Azure AD token support — if `api_key` is not set but `azure-identity` is available, use `DefaultAzureCredential` for token-based auth

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_azure_openai_provider.py -v
```

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/azure_openai_provider.py services/amplifier-providers/tests/test_azure_openai_provider.py && git commit -m "feat(azure): port Azure OpenAI provider with Azure AD token support"
```

---

### Task 4: Ollama Provider

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/ollama_provider.py`
- Create: `services/amplifier-providers/tests/test_ollama_provider.py`

Ollama runs local models via the `ollama` Python SDK. Simpler API than cloud providers — no rate limiting, no auth tokens. Key features:
- Connects to local Ollama server (default `http://localhost:11434`)
- Tool support depends on model capability
- No usage token tracking (some models don't report tokens)

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_ollama_provider.py`:

```python
"""Tests for OllamaProvider conversion logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    ToolSpec,
    Usage,
)


class TestOllamaInit:
    def test_init_defaults(self) -> None:
        from amplifier_providers.providers.ollama_provider import OllamaProvider
        p = OllamaProvider()
        assert p.name == "ollama"

    def test_init_with_host(self) -> None:
        from amplifier_providers.providers.ollama_provider import OllamaProvider
        p = OllamaProvider(config={"host": "http://custom:11434"})
        assert p.name == "ollama"


class TestOllamaConvertMessages:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.ollama_provider import OllamaProvider
        return OllamaProvider(config={"model": "llama3.1"})

    def test_simple_user_message(self) -> None:
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_system_message(self) -> None:
        p = self._make_provider()
        messages = [
            Message(role="system", content="Be helpful"),
            Message(role="user", content="Hello"),
        ]
        result = p._convert_messages(messages)
        assert result[0]["role"] == "system"


class TestOllamaConvertResponse:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.ollama_provider import OllamaProvider
        return OllamaProvider(config={"model": "llama3.1"})

    def test_text_response(self) -> None:
        p = self._make_provider()
        mock_response = {
            "message": {"role": "assistant", "content": "Hello from Ollama!"},
            "done": True,
            "eval_count": 25,
            "prompt_eval_count": 50,
        }
        result = p._convert_to_chat_response(mock_response)
        assert isinstance(result, ChatResponse)
        assert result.content is not None


class TestOllamaComplete:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.ollama_provider import OllamaProvider
        return OllamaProvider(config={"model": "llama3.1"})

    async def test_complete_returns_chat_response(self) -> None:
        p = self._make_provider()

        mock_response = {
            "message": {"role": "assistant", "content": "Hello!"},
            "done": True,
            "eval_count": 25,
            "prompt_eval_count": 50,
        }

        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        response = await p.complete(request)
        assert isinstance(response, ChatResponse)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_ollama_provider.py -v
```

**Step 3: Implement the Ollama provider**

Replace `services/amplifier-providers/src/amplifier_providers/providers/ollama_provider.py`. The implementation must:

- `__init__(self, config: dict | None = None)` — reads `host` from config or `OLLAMA_HOST` env var (default `http://localhost:11434`), `model` from config (default `llama3.1`), lazy client init via `ollama.AsyncClient`
- `_convert_messages(self, messages)` — Amplifier Message → Ollama format (similar to OpenAI: `{"role": ..., "content": ...}`)
- `_convert_tools_from_request(self, tools)` — ToolSpec → Ollama tool format (OpenAI-compatible function format)
- `_convert_to_chat_response(self, response)` — Ollama dict response → ChatResponse. Ollama returns dicts, not objects. Token counts from `eval_count`/`prompt_eval_count`.
- `complete(self, request, **kwargs)` — calls `client.chat()`, handles tool calls if model supports them
- Minimal error handling (connection errors, model not found)

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_ollama_provider.py -v
```

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/ollama_provider.py services/amplifier-providers/tests/test_ollama_provider.py && git commit -m "feat(ollama): port Ollama provider for local model support"
```

---

### Task 5: vLLM Provider

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/vllm_provider.py`
- Create: `services/amplifier-providers/tests/test_vllm_provider.py`

vLLM uses the OpenAI-compatible API endpoint. It uses the `openai` SDK pointed at a vLLM server. **It should share conversion code with the OpenAI provider** if upstream does.

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_vllm_provider.py`:

```python
"""Tests for VllmProvider."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    Usage,
)


class TestVllmInit:
    def test_init_defaults(self) -> None:
        from amplifier_providers.providers.vllm_provider import VllmProvider
        p = VllmProvider()
        assert p.name == "vllm"

    def test_init_with_base_url(self) -> None:
        from amplifier_providers.providers.vllm_provider import VllmProvider
        p = VllmProvider(config={"api_base": "http://localhost:8000/v1"})
        assert p.name == "vllm"


class TestVllmConvertMessages:
    """vLLM uses OpenAI-compatible format — conversion should match OpenAI."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.vllm_provider import VllmProvider
        return VllmProvider(config={"api_base": "http://localhost:8000/v1"})

    def test_simple_user_message(self) -> None:
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestVllmComplete:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.vllm_provider import VllmProvider
        return VllmProvider(config={"api_base": "http://localhost:8000/v1", "model": "meta-llama/Llama-3.1-8B"})

    async def test_complete_returns_chat_response(self) -> None:
        p = self._make_provider()

        mock_message = MagicMock()
        mock_message.content = "Hello from vLLM!"
        mock_message.role = "assistant"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 25
        mock_usage.total_tokens = 75

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "meta-llama/Llama-3.1-8B"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        response = await p.complete(request)
        assert isinstance(response, ChatResponse)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_vllm_provider.py -v
```

**Step 3: Implement the vLLM provider**

Replace `services/amplifier-providers/src/amplifier_providers/providers/vllm_provider.py`. The implementation must:

- `__init__(self, config: dict | None = None)` — reads `api_base` from config or `VLLM_API_BASE` env var (default `http://localhost:8000/v1`), `api_key` from config or `VLLM_API_KEY` env var (default `"EMPTY"` — vLLM doesn't require auth by default), `model` from config
- **Reuse OpenAI conversion methods** — vLLM is OpenAI-compatible. Import shared conversion code from `openai_provider.py` or use inheritance/delegation as upstream does.
- `complete(self, request, **kwargs)` — uses `openai.AsyncOpenAI(base_url=api_base)` pointed at the vLLM endpoint
- Minimal error handling (connection refused, model not loaded)

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_vllm_provider.py -v
```

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/vllm_provider.py services/amplifier-providers/tests/test_vllm_provider.py && git commit -m "feat(vllm): port vLLM provider using OpenAI-compatible API"
```

---

### Task 6: GitHub Copilot Provider

**Files:**
- Modify: `services/amplifier-providers/src/amplifier_providers/providers/github_copilot_provider.py`
- Create: `services/amplifier-providers/tests/test_github_copilot_provider.py`

GitHub Copilot uses an OpenAI-compatible API with Copilot-specific authentication. The upstream may use `github-copilot-sdk` for token management.

**Step 1: Write the failing tests**

Create `services/amplifier-providers/tests/test_github_copilot_provider.py`:

```python
"""Tests for GitHubCopilotProvider."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_protocol import (
    ChatRequest,
    ChatResponse,
    Message,
    Usage,
)


class TestGitHubCopilotInit:
    def test_init_defaults(self) -> None:
        from amplifier_providers.providers.github_copilot_provider import GitHubCopilotProvider
        p = GitHubCopilotProvider()
        assert p.name == "github_copilot"

    def test_init_with_token(self) -> None:
        from amplifier_providers.providers.github_copilot_provider import GitHubCopilotProvider
        p = GitHubCopilotProvider(config={"github_token": "ghp_test123"})
        assert p.name == "github_copilot"


class TestGitHubCopilotConvertMessages:
    """Copilot uses OpenAI-compatible format."""

    def _make_provider(self) -> Any:
        from amplifier_providers.providers.github_copilot_provider import GitHubCopilotProvider
        return GitHubCopilotProvider(config={"github_token": "ghp_test123"})

    def test_simple_user_message(self) -> None:
        p = self._make_provider()
        messages = [Message(role="user", content="Hello")]
        result = p._convert_messages(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestGitHubCopilotComplete:
    def _make_provider(self) -> Any:
        from amplifier_providers.providers.github_copilot_provider import GitHubCopilotProvider
        return GitHubCopilotProvider(config={"github_token": "ghp_test123"})

    async def test_complete_returns_chat_response(self) -> None:
        p = self._make_provider()

        mock_message = MagicMock()
        mock_message.content = "Hello from Copilot!"
        mock_message.role = "assistant"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 25
        mock_usage.total_tokens = 75

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        p._client = mock_client

        request = ChatRequest(messages=[Message(role="user", content="Hello")])
        response = await p.complete(request)
        assert isinstance(response, ChatResponse)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_github_copilot_provider.py -v
```

**Step 3: Implement the GitHub Copilot provider**

Replace `services/amplifier-providers/src/amplifier_providers/providers/github_copilot_provider.py`. The implementation must:

- `__init__(self, config: dict | None = None)` — reads `github_token` from config or `GITHUB_TOKEN` env var, lazy client init
- **Reuse OpenAI conversion methods** — Copilot is OpenAI-compatible. Same message/tool/response format.
- Copilot-specific auth: uses the GitHub token to obtain a Copilot session token via the Copilot API, then creates an `openai.AsyncOpenAI` client with that token and the Copilot endpoint URL
- `complete(self, request, **kwargs)` — uses the Copilot-authenticated OpenAI client
- Error handling for token expiry, auth failure

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_github_copilot_provider.py -v
```

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/src/amplifier_providers/providers/github_copilot_provider.py services/amplifier-providers/tests/test_github_copilot_provider.py && git commit -m "feat(copilot): port GitHub Copilot provider with Copilot authentication"
```

---

### Task 7: Update `test_describe.py` and README.md

**Files:**
- Modify: `services/amplifier-providers/tests/test_describe.py`
- Modify: `services/amplifier-providers/pyproject.toml` (if dependency updates needed)
- Create or Modify: `services/amplifier-providers/README.md`

**Step 1: Update `test_describe.py`**

After Phase 2 (Anthropic) and Phase 3 (all 6 others), **no providers are stubs anymore**. Delete the `test_stub_providers_raise_not_implemented` test function entirely (lines 88–116 of `services/amplifier-providers/tests/test_describe.py`).

Also delete `test_stub_provider_files_exist` (lines 69–85) since the concept of "stub files" no longer applies — they're all real providers now.

The remaining tests (`test_scan_package_discovers_all_providers`, `test_describe_reports_all_8_providers`, `test_describe_reports_zero_tools`, `test_describe_reports_zero_hooks`) should still pass unchanged.

**Step 2: Run tests to verify**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/test_describe.py -v
```

Expected: All remaining tests PASS. The deleted tests are gone.

**Step 3: Run full test suite**

```bash
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/ -v
```

Expected: All tests PASS across all test files.

**Step 4: Create/update README.md**

Create `services/amplifier-providers/README.md` with configuration documentation for all 8 providers:

```markdown
# amplifier-providers

LLM provider adapters for Amplifier IPC.

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

Install with specific provider extras:

    pip install amplifier-providers[anthropic]
    pip install amplifier-providers[openai]
    pip install amplifier-providers[azure]
    pip install amplifier-providers[gemini]
    pip install amplifier-providers[ollama]
    pip install amplifier-providers[all]

## Dropped from Upstream

These methods exist in the upstream v1 providers but are not part of the IPC protocol:

- `get_info()` — provider metadata / capability reporting
- `list_models()` — model discovery
- `close()` — client cleanup
- `mount()` / `__amplifier_module_type__` — v1 lifecycle

These may be added to the IPC protocol in future versions.
```

**Step 5: Commit**

```bash
cd amplifier-ipc && git add services/amplifier-providers/tests/test_describe.py services/amplifier-providers/README.md && git commit -m "chore: remove stub tests, add provider README with configuration docs"
```

---

### Task 8: Create Foundation Agent Definition YAML

**Files:**
- Create: `definitions/foundation-agent.yaml`

This creates the agent definition YAML file that can be registered with `$AMPLIFIER_HOME` and used with `amplifier-ipc run --agent foundation`.

**Step 1: Create the definitions directory**

```bash
mkdir -p amplifier-ipc/definitions
```

**Step 2: Create the foundation agent definition**

Create `definitions/foundation-agent.yaml`:

```yaml
agent:
  local_ref: foundation
  uuid: 3898a638-71de-427a-8183-b80eba8b26be
  version: 1
  description: Foundation agent — core orchestrator, tools, hooks, and content.

  orchestrator: foundation:streaming
  context_manager: foundation:simple
  provider: providers:anthropic

  tools: true
  hooks: true
  agents: true
  context: true

  service:
    installer: uv
    source: git+https://github.com/microsoft/amplifier-ipc@main#subdirectory=/services/amplifier-foundation
```

This definition:
- References the `streaming` orchestrator and `simple` context manager from the foundation service
- Sets the default provider to `providers:anthropic` (configurable at session level)
- Enables all tools, hooks, agents, and context from its backing service
- Points to the foundation service for installation

**Step 3: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('amplifier-ipc/definitions/foundation-agent.yaml')); print('Valid YAML')"
```

Expected: `Valid YAML`

**Step 4: Commit**

```bash
cd amplifier-ipc && git add definitions/foundation-agent.yaml && git commit -m "feat: add foundation agent definition YAML"
```

---

### Task 9: End-to-End Smoke Test (Mock Provider — Automated)

**Files:**
- Create: `amplifier-ipc-host/tests/test_e2e_mock.py`

This test exercises the full chain with no API key required, using the mock provider. It proves that: host spawns services → describe works → orchestrator runs → mock provider returns a response → events flow correctly.

**Step 1: Write the test**

Create `amplifier-ipc-host/tests/test_e2e_mock.py`:

```python
"""End-to-end smoke test using mock provider — no API key required.

Exercises the full chain:
  SessionConfig → Host → spawn services → describe → registry → router →
  orchestrator.execute → request.provider_complete (mock) → response → events

This test requires the amplifier-foundation and amplifier-providers service
packages to be installed in the test environment.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from amplifier_ipc_host.config import HostSettings, ServiceOverride, SessionConfig
from amplifier_ipc_host.events import CompleteEvent, HostEvent, StreamTokenEvent
from amplifier_ipc_host.host import Host

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FOUNDATION_SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "amplifier-foundation"
)
PROVIDERS_SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "amplifier-providers"
)


def _service_override(service_dir: Path) -> ServiceOverride:
    """Build a ServiceOverride that runs the service from its source directory."""
    return ServiceOverride(
        command=["python", "-m", service_dir.name.replace("-", "_")],
        working_dir=str(service_dir),
    )


def _make_mock_session_config() -> SessionConfig:
    """Build a minimal SessionConfig using mock provider."""
    return SessionConfig(
        services=[
            "amplifier-foundation-serve",
            "amplifier-providers-serve",
        ],
        orchestrator="streaming",
        context_manager="simple",
        provider="mock",
    )


def _make_settings() -> HostSettings:
    """Build HostSettings with service overrides pointing to local source."""
    return HostSettings(
        service_overrides={
            "amplifier-foundation-serve": ServiceOverride(
                command=[
                    "python", "-m", "amplifier_foundation",
                ],
                working_dir=str(FOUNDATION_SERVICE_DIR),
            ),
            "amplifier-providers-serve": ServiceOverride(
                command=[
                    "python", "-m", "amplifier_providers",
                ],
                working_dir=str(PROVIDERS_SERVICE_DIR),
            ),
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_e2e_mock_provider_completes() -> None:
    """Full e2e: host spawns services, runs orchestrator, mock provider responds."""
    config = _make_mock_session_config()
    settings = _make_settings()
    host = Host(config, settings)

    events: list[HostEvent] = []
    async for event in host.run("Say hello"):
        events.append(event)
        if isinstance(event, CompleteEvent):
            break

    # Must have at least a CompleteEvent
    assert any(isinstance(e, CompleteEvent) for e in events), (
        f"No CompleteEvent in events: {[type(e).__name__ for e in events]}"
    )

    # The complete event should have a non-empty result
    complete = next(e for e in events if isinstance(e, CompleteEvent))
    assert complete.result is not None
```

**Step 2: Run the test**

```bash
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_e2e_mock.py -v -m slow --timeout=60
```

Expected: This test may fail initially if the service processes can't be spawned from the test environment (virtualenv/PATH issues). Debug as needed — the key is proving the Host → service → orchestrator → provider → response chain works.

If the services can't be spawned directly, mark the test with `@pytest.mark.skipif` and add a note about required setup:

```python
@pytest.mark.skipif(
    not FOUNDATION_SERVICE_DIR.exists() or not PROVIDERS_SERVICE_DIR.exists(),
    reason="Requires local service packages installed",
)
```

**Step 3: Commit**

```bash
cd amplifier-ipc && git add amplifier-ipc-host/tests/test_e2e_mock.py && git commit -m "test: add end-to-end smoke test with mock provider"
```

---

### Task 10: End-to-End Smoke Test (Real Anthropic — Manual)

**Files:**
- Create: `tests/test_e2e_anthropic.py` (at the monorepo root)

This is a manual test that exercises the full chain with a real Anthropic API call. It requires `ANTHROPIC_API_KEY` to be set and is skipped in CI.

**Step 1: Create the test directory if needed**

```bash
mkdir -p amplifier-ipc/tests
touch amplifier-ipc/tests/__init__.py
```

**Step 2: Write the test**

Create `tests/test_e2e_anthropic.py`:

```python
"""End-to-end smoke test with real Anthropic API — requires ANTHROPIC_API_KEY.

This test is gated behind the ANTHROPIC_API_KEY env var and is NOT run in CI.
It exercises the full chain:
  Host → spawn services → describe → orchestrator → Anthropic provider →
  real API call → LLM response → events

Run manually:
    ANTHROPIC_API_KEY=sk-... python -m pytest tests/test_e2e_anthropic.py -v -s --timeout=120
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from amplifier_ipc_host.config import HostSettings, ServiceOverride, SessionConfig
from amplifier_ipc_host.events import CompleteEvent, HostEvent, StreamTokenEvent
from amplifier_ipc_host.host import Host

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

FOUNDATION_SERVICE_DIR = (
    Path(__file__).resolve().parents[1] / "services" / "amplifier-foundation"
)
PROVIDERS_SERVICE_DIR = (
    Path(__file__).resolve().parents[1] / "services" / "amplifier-providers"
)


def _make_anthropic_session_config() -> SessionConfig:
    return SessionConfig(
        services=[
            "amplifier-foundation-serve",
            "amplifier-providers-serve",
        ],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
        component_config={
            "anthropic": {
                "api_key": ANTHROPIC_API_KEY,
                "model": "claude-sonnet-4-20250514",
            }
        },
    )


def _make_settings() -> HostSettings:
    return HostSettings(
        service_overrides={
            "amplifier-foundation-serve": ServiceOverride(
                command=["python", "-m", "amplifier_foundation"],
                working_dir=str(FOUNDATION_SERVICE_DIR),
            ),
            "amplifier-providers-serve": ServiceOverride(
                command=["python", "-m", "amplifier_providers"],
                working_dir=str(PROVIDERS_SERVICE_DIR),
            ),
        }
    )


@pytest.mark.skipif(
    not ANTHROPIC_API_KEY,
    reason="ANTHROPIC_API_KEY not set — skipping real API test",
)
@pytest.mark.slow
async def test_e2e_anthropic_real_api() -> None:
    """Full e2e with real Anthropic API: host → orchestrator → Anthropic → response."""
    config = _make_anthropic_session_config()
    settings = _make_settings()
    host = Host(config, settings)

    events: list[HostEvent] = []
    tokens: list[str] = []

    async for event in host.run("What is 2 + 2? Reply with just the number."):
        events.append(event)
        if isinstance(event, StreamTokenEvent):
            tokens.append(event.token)
            print(event.token, end="", flush=True)  # Live token display
        if isinstance(event, CompleteEvent):
            break

    print()  # newline after streaming

    # Must have a CompleteEvent
    assert any(isinstance(e, CompleteEvent) for e in events), (
        f"No CompleteEvent: {[type(e).__name__ for e in events]}"
    )

    # Should have received at least some streaming tokens (if streaming is wired)
    # or at minimum a complete response
    complete = next(e for e in events if isinstance(e, CompleteEvent))
    assert complete.result is not None
    print(f"\nFull response: {complete.result}")
    print(f"Streaming tokens received: {len(tokens)}")
    print(f"Total events: {len(events)}")
```

**Step 3: Run the test manually (requires API key)**

```bash
cd amplifier-ipc && ANTHROPIC_API_KEY=sk-... python -m pytest tests/test_e2e_anthropic.py -v -s --timeout=120
```

Expected: The test calls the real Anthropic API, receives a response (likely "4"), and completes with a `CompleteEvent`.

**Step 4: Verify it skips without API key**

```bash
cd amplifier-ipc && python -m pytest tests/test_e2e_anthropic.py -v
```

Expected: Test is SKIPPED with reason "ANTHROPIC_API_KEY not set".

**Step 5: Commit**

```bash
cd amplifier-ipc && git add tests/ && git commit -m "test: add end-to-end smoke test with real Anthropic API (manual, API key gated)"
```

---

## Post-Implementation Verification

After all 10 tasks are complete, run the full test suite:

```bash
# Provider unit tests
cd amplifier-ipc/services/amplifier-providers && python -m pytest tests/ -v

# Host tests (including e2e mock)
cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v

# Protocol tests
cd amplifier-ipc/amplifier-ipc-protocol && python -m pytest tests/ -v
```

All tests should pass. The provider service should report 8 real providers (no stubs) in its `describe` response.

## Provider SDK Dependency Notes

The `pyproject.toml` at `services/amplifier-providers/pyproject.toml` already declares optional dependency groups for each provider:

```toml
[project.optional-dependencies]
anthropic = ["anthropic"]
openai = ["openai"]
azure = ["openai", "azure-identity"]
gemini = ["google-generativeai"]
ollama = ["ollama"]
vllm = ["openai"]
copilot = ["openai"]
```

Each provider's `__init__` must handle the case where its SDK is not installed by catching `ImportError` and raising a clear error message (same pattern as the Anthropic provider's lazy client init).