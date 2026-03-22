"""amplifier-ipc-protocol: IPC protocol definitions for Amplifier Lite.

Provides the full public API for building JSON-RPC 2.0 IPC packages:

    from amplifier_ipc.protocol import tool, Server, Client

    @tool
    class MyTool:
        name = "my_tool"
        description = "Does something useful"
        input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

        async def execute(self, input):
            return input["text"].upper()

    # Run as a service (reads from stdin, writes to stdout):
    if __name__ == "__main__":
        Server("my_package").run()
"""

from amplifier_ipc.protocol.client import Client
from amplifier_ipc.protocol.decorators import (
    context_manager,
    hook,
    orchestrator,
    provider,
    tool,
)
from amplifier_ipc.protocol.errors import JsonRpcError
from amplifier_ipc.protocol.models import (
    ChatRequest,
    ChatResponse,
    HookAction,
    HookResult,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolCallBlock,
    ToolResult,
    ToolSpec,
    Usage,
)
from amplifier_ipc.protocol.protocols import (
    ContextManagerProtocol,
    HookProtocol,
    OrchestratorProtocol,
    ProviderProtocol,
    ToolProtocol,
)
from amplifier_ipc.protocol.server import Server

__all__ = [
    # Decorators
    "tool",
    "hook",
    "orchestrator",
    "context_manager",
    "provider",
    # Models
    "ToolCall",
    "ToolSpec",
    "ToolResult",
    "Message",
    "HookAction",
    "HookResult",
    "ChatRequest",
    "ChatResponse",
    "TextBlock",
    "ThinkingBlock",
    "ToolCallBlock",
    "Usage",
    # Protocols
    "ToolProtocol",
    "HookProtocol",
    "OrchestratorProtocol",
    "ContextManagerProtocol",
    "ProviderProtocol",
    # Infrastructure
    "Server",
    "Client",
    "JsonRpcError",
]
