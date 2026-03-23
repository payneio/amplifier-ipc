Well, I'm genuinely out of ideas, then. How would we enable a person to configure a base agent with additional behaviors using just a yaml file while avoiding dependency conflicts?
The tension is real: YAML configurability, dependency isolation, and simplicity — pick two.

But I think the framing might be slightly off. Dependency conflicts are a packaging problem, not a composition problem. No amount of YAML magic helps if ToolA needs numpy 1.x and ToolB needs numpy 2.x — they can't coexist in the same Python process regardless of how you wire them.

So there are really only two models:

Model 1: Single venv, conflicts caught at install time. User writes a YAML saying "I want base agent X with tools Y and Z." All of those get installed into one venv. If there's a dependency conflict, uv tells you at install time, not at runtime. YAML is a thin configuration layer over what's already installed. This handles 95% of real cases — conflicting deps between tools in the same agent are genuinely rare.

Model 2: Multi-process, each component isolated. Tools run as separate subprocesses with their own venvs, communicating via IPC. This is literally what MCP does — tool servers are independent processes. Handles conflicting deps but at significant complexity and latency cost.

For Model 1, the lightest possible YAML layer would be:


# User's agent config — references names, not class paths
agent:
  base: foundation/default
  tools:
    - bash:
        timeout: 60
    - read-file
    - skills:
        bundles:
          - git+https://github.com/microsoft/amplifier-bundle-skills@main
  hooks:
    - deprecation
Components register by name via entry points. The resolver looks up what's installed, applies config overrides, builds the session. No import_and_create(), no class-path strings — just "give me the thing called bash with this config." Dependency conflicts are pip/uv's problem, not yours.

The honest answer to your question might be: you can't avoid dependency conflicts at the YAML level. You either accept that one venv means one compatible dependency set (and use multiple environments for truly incompatible combinations), or you go multi-process like MCP. The YAML configuration question and the dependency isolation question are orthogonal — solve them separately.

show me how mcp does it
Web SearchModel Context Protocol MCP architecture tool servers subprocess isolation 2025
OUT
Web search results for query: "Model Context Protocol MCP architecture tool servers subprocess isolation 2025"

Links: [{"title":"Specification - Model Context Protocol","url":"https://modelcontextprotocol.io/specification/2025-11-25"},{"title":"Model Context Protocol - Wikipedia","url":"https://en.wikipedia.org/wiki/Model_Context_Protocol"},{"title":"What is Model Context Protocol (MCP) in 2025 - F22 Labs","url":"https://www.f22labs.com/blogs/what-is-model-context-protocol-mcp-in-2025/"},{"title":"The Definitive Guide to Model Context Protocol (MCP) in 2025 | Data Science Dojo","url":"https://datasciencedojo.com/blog/guide-to-model-context-protocol/"},{"title":"Model Context Protocol (MCP): Architecture, Components & Workflow","url":"https://www.kubiya.ai/blog/model-context-protocol-mcp-architecture-components-and-workflow"},{"title":"Securing the Model Context Protocol (MCP): Risks, Controls, and Governance","url":"https://arxiv.org/html/2511.20920v1"},{"title":"Model Context Protocol (MCP) explained: A practical technical overview for developers and architects","url":"https://codilime.com/blog/model-context-protocol-explained/"},{"title":"model-context-protocol-resources/guides/mcp-server-development-guide.md at main · cyanheads/model-context-protocol-resources","url":"https://github.com/cyanheads/model-context-protocol-resources/blob/main/guides/mcp-server-development-guide.md"},{"title":"The Model Context Protocol (MCP): A Comprehensive Technical Report - DEV Community","url":"https://dev.to/luzkalidgm/the-model-context-protocol-mcp-a-comprehensive-technical-report-470d"},{"title":"What is Model Context Protocol (MCP): Explained - Composio","url":"https://composio.dev/blog/what-is-model-context-protocol-mcp-explained"}]

I've found comprehensive information about the Model Context Protocol (MCP) architecture, tool servers, and subprocess isolation. Here's what I found:

## MCP Architecture Overview

MCP defines a client-server architecture where the MCP Host is the AI application that coordinates and manages one or multiple MCP clients, and each MCP Client maintains a connection to an MCP server and obtains context from it.

The MCP architecture follows a modular client–server design that cleanly separates the Host Application, MCP Client, and MCP Server, ensuring predictable and scalable integrations.

## Tool Servers

On the server side, MCP supports prompts, resources, and tools, while on the client side, MCP defines primitives including roots, sampling, and elicitation.

Each client is created by the host and maintains an isolated server connection, establishing one stateful session per server and maintaining security boundaries between servers.

## Subprocess Isolation

In Model Context Protocol, the host launches the server as a subprocess and uses these streams for communication, where the host writes JSON-RPC messages to the server's stdin, and the server writes responses to its stdout.

The Host spawns the Server as a subprocess, which provides high security through process isolation and zero network latency.

The protocol defines two standard transport mechanisms for client–server communication: a stdio transport, in which the client launches the MCP server as a subprocess and exchanges JSON-RPC messages over standard input and output, and a Streamable HTTP transport, which uses HTTP POST and GET requests.

## Communication Protocol

All messages exchanged between clients and servers are encoded using JSON-RPC 2.0, and JSON-RPC messages must be UTF-8 encoded.


REMINDER: You MUST include the sources above in your response to the user using markdown hyperlinks.
Web Fetchhttps://modelcontextprotocol.io/specification/2025-11-25
Fetched from https://modelcontextprotocol.io/specification/2025-11-25
Web Fetchhttps://modelcontextprotocol.io/specification/2025-11-25/architecture
Fetched from https://modelcontextprotocol.io/specification/2025-11-25/architecture
Here's how MCP does it:

The Architecture

┌─────────────────────────────────────────┐
│           Host (your agent app)         │
│                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐│
│  │ Client 1 │ │ Client 2 │ │ Client 3 ││
│  └────┬─────┘ └────┬─────┘ └────┬─────┘│
└───────┼─────────────┼─────────────┼─────┘
        │ stdio       │ stdio       │ HTTP
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐
   │ Server 1 │  │ Server 2 │  │ Server 3 │
   │ (bash,   │  │ (db      │  │ (external│
   │  files)  │  │  tools)  │  │  APIs)   │
   │ Own venv │  │ Own venv │  │ Remote   │
   └─────────┘  └──────────┘  └──────────┘
Key design:

Each server is a separate process. The host spawns it as a subprocess (stdio transport) or connects to it over HTTP. Complete process isolation — each server has its own Python environment, its own dependencies, its own everything.

Communication is JSON-RPC 2.0 over stdin/stdout. The host writes a JSON-RPC message to the server's stdin, the server writes its response to stdout. No shared memory, no shared imports, no dependency conflicts possible.

1:1 client-to-server mapping. The host creates one client per server. Each client maintains one stateful session. Servers can't see each other or the full conversation — the host controls what context each server receives.

Tool call flow:

LLM says "call tool X"
Host figures out which server owns tool X
Host's client for that server sends a JSON-RPC tools/call request over stdio
Server executes the tool in its own process/venv
Server returns the result as JSON-RPC response
Host feeds result back to the LLM
Capability negotiation at startup. When a server is launched, it tells the client what it can do (which tools, resources, prompts it offers). No YAML manifest needed — the server self-describes.

What this means for your question
MCP solves both problems simultaneously:

No dependency conflicts: each server is a separate process with its own environment
YAML-like configuration: the host just needs a list of servers to launch — you configure which servers to include, not which classes to load
A typical MCP config (e.g., in Claude Desktop) looks like:


{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    },
    "database": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db", "mydb.sqlite"]
    }
  }
}
That's it. No class paths, no dynamic import, no dependency resolution. Each server is a standalone executable. The host just needs to know how to launch it and then speaks JSON-RPC.

The cost: serialization overhead on every tool call (JSON over stdio instead of a Python function call), and you lose in-process access to shared state. But you gain total isolation and a genuinely simple composition model.

Sources:

MCP Specification
MCP Architecture
what about hooks?
MCP doesn't have them. The protocol defines three server primitives — tools, resources, and prompts — and that's it. There's no lifecycle event system, no middleware pipeline, no way for a server to intercept another server's tool call or inject context before a provider request.

In MCP, all of that orchestration logic lives in the host. The host owns the conversation loop, decides when to call tools, manages context, talks to the LLM. If you want hook-like behavior (approve before tool execution, inject context, modify requests), the host implements it directly — it's not a pluggable concern.

This maps to what we discussed earlier about the infrastructure-vs-plugin distinction. In amplifier-lite's taxonomy:

Component	MCP equivalent
Tools	MCP servers (isolated processes)
Providers	Host-internal (not pluggable via MCP)
Hooks	Host-internal (not pluggable via MCP)
Orchestrator	Host-internal (not pluggable via MCP)
Context manager	Host-internal (not pluggable via MCP)
MCP only externalizes the plugin components (tools) into separate processes. The infrastructure components (orchestration, hooks, context management, provider calls) stay in the host — which is exactly the split you identified earlier as the natural boundary.

So if you adopted an MCP-like model, hooks would be part of your core library, not something loaded from external packages. Which circles back to your earlier observation that orchestrator and context manager are never composed from multiple packages — hooks might belong in that same "infrastructure" category, configured rather than plugged in.

how many components (orchestorators, context managers, hooks, toolls, providers) do we have in use in our amplifier-lit/packages/foundation package?
Task:Count foundation package components
IN
In /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/, find all the actual component implementations. I need a count of:

1. **Orchestrators** - classes that implement the Orchestrator protocol (look in orchestrators/ directory)
2. **Context managers** - classes that implement the ContextManager protocol (look in context_managers/ directory)
3. **Hooks** - classes that implement the Hook protocol (look in hooks/ directory)
4. **Tools** - classes that implement the Tool protocol (look in tools/ directory and subdirectories)
5. **Providers** - classes that implement the Provider protocol (look in providers/ directory)

For each category, list the actual class names and file paths. Don't count base classes or abstract classes — only concrete implementations that would be referenced in a session config.
Bash Find all relevant directories in amplifier-foundation
IN
find /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation -type d -name "orchestrators" -o -type d -name "context_managers" -o -type d -name "hooks" -o -type d -name "tools" -o -type d -name "providers" | head -20

OUT
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/hooks
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/orchestrators
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/context_managers
Bash List orchestrators directory contents
IN
ls -la /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/orchestrators/

OUT
total 68
drwxrwxr-x  3 payne payne  4096 Mar 19 15:58 .
drwxrwxr-x 12 payne payne  4096 Mar 19 08:02 ..
drwxrwxr-x  2 payne payne  4096 Mar 19 22:13 __pycache__
-rw-rw-r--  1 payne payne 55140 Mar 19 16:24 streaming.py
Bash List context_managers directory contents
IN
ls -la /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/context_managers/

OUT
total 60
drwxrwxr-x  3 payne payne  4096 Mar 19 15:55 .
drwxrwxr-x 12 payne payne  4096 Mar 19 08:02 ..
drwxrwxr-x  2 payne payne  4096 Mar 19 16:07 __pycache__
-rw-rw-r--  1 payne payne 48551 Mar 19 15:55 simple.py
Bash List hooks directory contents
IN
ls -la /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/hooks/

OUT
total 136
drwxrwxr-x  6 payne payne  4096 Mar 19 16:47 .
drwxrwxr-x 12 payne payne  4096 Mar 19 08:02 ..
drwxrwxr-x  3 payne payne  4096 Mar 19 16:45 approval
-rw-rw-r--  1 payne payne  7551 Mar 19 06:29 deprecation.py
-rw-rw-r--  1 payne payne  3348 Mar 19 06:30 logging.py
-rw-rw-r--  1 payne payne  6548 Mar 19 16:45 progress_monitor.py
drwxrwxr-x  2 payne payne  4096 Mar 19 11:57 __pycache__
-rw-rw-r--  1 payne payne  3871 Mar 19 05:51 redaction.py
drwxrwxr-x  3 payne payne  4096 Mar 19 07:03 routing
-rw-rw-r--  1 payne payne 16936 Mar 19 16:47 session_naming.py
drwxrwxr-x  3 payne payne  4096 Mar 19 16:45 shell
-rw-rw-r--  1 payne payne 18762 Mar 19 16:45 status_context.py
-rw-rw-r--  1 payne payne 23349 Mar 19 06:47 streaming_ui.py
-rw-rw-r--  1 payne payne 12502 Mar 19 16:45 todo_display.py
-rw-rw-r--  1 payne payne  6520 Mar 19 16:45 todo_reminder.py
Bash List tools directory contents
IN
ls -la /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/

OUT
total 152
drwxrwxr-x 11 payne payne  4096 Mar 19 16:53 .
drwxrwxr-x 12 payne payne  4096 Mar 19 08:02 ..
drwxrwxr-x  4 payne payne  4096 Mar 19 07:03 apply_patch
drwxrwxr-x  3 payne payne  4096 Mar 19 16:49 bash
drwxrwxr-x  3 payne payne  4096 Mar 19 07:03 bundle_python_dev
drwxrwxr-x  3 payne payne  4096 Mar 19 11:02 bundle_shadow
-rw-rw-r--  1 payne payne 45554 Mar 19 16:53 delegate.py
drwxrwxr-x  3 payne payne  4096 Mar 19 16:49 filesystem
-rw-rw-r--  1 payne payne     0 Mar 19 05:51 __init__.py
drwxrwxr-x  3 payne payne  4096 Mar 19 11:14 mcp
drwxrwxr-x  2 payne payne  4096 Mar 19 11:57 __pycache__
drwxrwxr-x  3 payne payne  4096 Mar 19 16:52 recipes
drwxrwxr-x  3 payne payne  4096 Mar 19 07:03 search
-rw-rw-r--  1 payne payne 31044 Mar 19 16:51 task.py
-rw-rw-r--  1 payne payne  6577 Mar 19 16:48 todo.py
-rw-rw-r--  1 payne payne 17341 Mar 19 16:49 web.py
Bash Find providers directory
IN
find /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation -type d -name "providers"

OUT
0
Bash List all directories in amplifier_foundation
IN
ls -la /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/

OUT
total 52
drwxrwxr-x 12 payne payne 4096 Mar 19 08:02 .
drwxrwxr-x  3 payne payne 4096 Mar 19 05:51 ..
drwxrwxr-x  2 payne payne 4096 Mar 19 05:51 agents
drwxrwxr-x  2 payne payne 4096 Mar 19 05:51 behaviors
drwxrwxr-x  5 payne payne 4096 Mar 19 05:51 context
drwxrwxr-x  3 payne payne 4096 Mar 19 15:55 context_managers
drwxrwxr-x  6 payne payne 4096 Mar 19 16:47 hooks
-rw-rw-r--  1 payne payne  108 Mar 19 05:51 __init__.py
drwxrwxr-x  3 payne payne 4096 Mar 19 15:58 orchestrators
drwxrwxr-x  2 payne payne 4096 Mar 19 11:57 __pycache__
drwxrwxr-x  2 payne payne 4096 Mar 19 05:51 recipes
drwxrwxr-x  2 payne payne 4096 Mar 19 05:51 sessions
drwxrwxr-x 11 payne payne 4096 Mar 19 16:53 tools
Bash Find all Python files in tools directory
IN
find /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools -type f -name "*.py" | grep -v __pycache__

OUT
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_python_dev/models.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_python_dev/checker.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_python_dev/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_python_dev/config.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/resource_wrapper.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/manager.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/content_utils.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/streamable_http_client.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/hooks.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/reconnection.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/client.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/wrapper.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/config.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/prompt_wrapper.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/filesystem/read.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/filesystem/path_validation.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/filesystem/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/filesystem/write.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/filesystem/edit.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bash/safety.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bash/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/web.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/task.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/delegate.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/gitea.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/manager.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/environment.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/container.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/snapshot.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/builder.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/models.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/__main__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/cli.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/bundle_shadow/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/search/grep.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/search/glob.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/search/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/todo.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/recipes/expression_evaluator.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/recipes/executor.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/recipes/models.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/recipes/session.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/recipes/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/recipes/validator.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/engines/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/engines/native.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/engines/function.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/tool.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/path_validation.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/__init__.py
/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/apply_diff.py
Grep "^class\s+\w+.*Tool" (in /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools)
14 lines of output
Grep "class\s+\w+.*Provider" (in /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation)
1 line of output
Read simple.py
Read approval_hook.py
Read __init__.py
Read streaming_ui.py
Read todo_reminder.py
Read status_context.py
Grep "^class\s+\w+" (in /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/filesystem/read.py)
1 line of output
Grep "^class\s+\w+" (in /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/apply_patch/tool.py)
1 line of output
Bash Search for provider-related files
IN
find /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation -name "*provider*" -o -name "*Provider*" | head -20

OUT
0
Grep "^class\s+\w+" (in /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/mcp/wrapper.py)
1 line of output
Grep "^class\s+\w+" (in /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/tools/web.py)
2 lines of output
Bash List all Python files in context_managers
IN
ls -1 /data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/context_managers/ | grep -v __pycache__

OUT
simple.py
Category	Count	Components
Orchestrators	1	StreamingOrchestrator
Context Managers	1	SimpleContextManager
Hooks	10	DeprecationHook, LoggingHook, ProgressMonitorHooks, ApprovalHook, StatusContextHook, SessionNamingHook, StreamingUIHooks, TodoDisplayHooks, TodoReminderHook, ShellHookBridge
Tools	14	BashTool, EditTool, ReadTool, WriteTool, GrepTool, GlobTool, MCPToolWrapper, TaskTool, TodoTool, WebSearchTool, WebFetchTool, ApplyPatchTool, RecipesTool, DelegateTool
Providers	0	(in separate packages)
This reinforces the pattern pretty starkly. The "infrastructure" components (orchestrator, context manager) are each exactly 1. The "plugin" components scale: 14 tools, 10 hooks.

And notice what the hooks actually are — most of them are UI/UX concerns (StreamingUIHooks, TodoDisplayHooks, ProgressMonitorHooks, SessionNamingHook) or operational concerns (LoggingHook, DeprecationHook, ApprovalHook). They're tightly coupled to the host application, not to external capabilities. None of them need dependency isolation. They're more like configurable middleware in a web framework than independent plugins.

The tools are the only components that genuinely benefit from being externalized — they interact with external systems (filesystem, shell, web, MCP servers) and could plausibly have conflicting dependencies.

ok. So it looks like an agent could have around 50 different components it uses. I guess I'm wondering if, instead of package.modules we were to write each component as its own service that registers with a central host how much work that would be.
Let's think through this concretely by component type.

Tools (14) — Easiest. The interface is already service-shaped: input_schema for discovery, execute(input) -> ToolResult for invocation. MCP literally defines this protocol. You'd write a thin JSON-RPC wrapper, and since you already have MCPToolWrapper on the client side, the host can already consume them. Realistic work: a generic tool-server harness (~1 day), then ~30 min per tool to wrap. Maybe 3-4 days for all 14.

Hooks (10) — This is where it gets painful. Hooks fire on every event in the hot path. A single tool call currently emits tool:pre, executes, then tool:post. With 10 hooks as services, that's up to 20 IPC round-trips per tool call — JSON serialize, write to stdin, read from stdout, deserialize, for each one. And hooks like MODIFY transform data in-flight, so they're sequential, not parallelizable. You'd also need to serialize the full event data (which includes Message objects, tool arguments, provider requests) for every dispatch. The latency would be noticeable.

Orchestrator (1) — Doesn't make sense as a service. It is the main loop — it calls the provider, dispatches tools, manages context. If you externalize it, the host becomes a dumb relay and everything flows through IPC twice.

Context Manager (1) — Same problem. add_message() and get_messages_for_request() are called constantly during the orchestration loop. Making them cross-process adds latency to every LLM call.

Providers (in other packages) — Already making HTTP calls to external APIs. Adding a JSON-RPC layer in front of an HTTP call just adds latency for no isolation benefit.

Realistic breakdown
Component type	As a service?	Work	Worth it?
Tools (14)	Natural fit	3-4 days	Yes — MCP already defines this
Hooks (10)	Awkward	5-7 days	No — latency kills you
Orchestrator (1)	No	—	It is the host
Context manager (1)	No	—	Too hot-path
Providers	Marginal	2-3 days	Already doing HTTP
The honest answer: tools are the only components where service extraction makes sense, and MCP already solved that problem. The other ~36 components are better off as in-process code because they're either infrastructure (orchestrator, context manager) or middleware in the hot path (hooks).

Which brings us back to a pretty clean split:

Tools → external services (MCP)
Everything else → your core library, configured not plugged
what are you talking about, latency doesn't "kill you" on any of this. The slowest part are the provider calls, which would dwarf any IPC latency.
You're right, I was being dramatic. The LLM round-trip is seconds. JSON-RPC over stdio is microseconds to low milliseconds. Even 20 hook dispatches per tool call would add maybe 10-20ms total — completely invisible next to a 2-5 second provider call.

So with latency off the table, the real question is just: is the engineering effort worth it? Let me re-evaluate hooks as services honestly.

The actual challenges with hooks as services aren't latency — they're:

Serialization surface area. Hook event data includes Message objects, tool arguments, provider requests/responses — all your Pydantic models need to round-trip through JSON. But they're already Pydantic, so .model_dump() / .model_validate() basically handles this.

Sequential dispatch with data mutation. MODIFY hooks transform the event data and pass it to the next hook. That's a chain of service calls where each depends on the previous result. Works fine, just sequential IPC.

Lifecycle management. Spawning and monitoring 10 hook subprocesses plus 14 tool subprocesses. Not hard, just plumbing.

None of these are blockers. It's all straightforward engineering.

Revised estimate for making everything a service: maybe 2-3 weeks of focused work. A generic JSON-RPC service harness, a host-side dispatcher, and then wrapping each component. The models are already serializable. The interfaces are already clean.

The more interesting question is whether you'd want all ~50 components as separate processes, or whether it makes more sense to group related ones into a smaller number of services (e.g., one "foundation hooks" server that exposes all 10 hooks, one "filesystem tools" server that exposes read/write/edit/glob/grep).

what would the engineering look like to turn one of these components as an ipc service?
Let me sketch it out concretely. Take BashTool as the example.

You need three things: a server wrapper, a client proxy, and a transport.

1. The transport (shared, write once)

# amplifier_lite/ipc/transport.py
import json, sys

async def send(message: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    line = json.dumps(message) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()

async def receive(stream) -> dict:
    """Read a JSON-RPC message from a stream."""
    line = await stream.readline()
    return json.loads(line)
2. The server wrapper (generic, write once)

# amplifier_lite/ipc/tool_server.py
import asyncio, json, sys

async def serve_tool(tool):
    """Expose any Tool instance as a JSON-RPC stdio server."""
    reader = asyncio.StreamReader()
    await asyncio.get_event_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )

    while True:
        line = await reader.readline()
        if not line:
            break
        request = json.loads(line)
        method = request["method"]

        if method == "describe":
            result = {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
        elif method == "execute":
            tool_result = await tool.execute(request["params"])
            result = tool_result.model_dump()
        
        response = {"id": request["id"], "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
3. BashTool as a service (one-liner entry point)

# amplifier_foundation/tools/bash/server.py
import asyncio
from amplifier_foundation.tools.bash import BashTool
from amplifier_lite.ipc.tool_server import serve_tool

if __name__ == "__main__":
    tool = BashTool(config={"timeout": 30})
    asyncio.run(serve_tool(tool))
4. The client proxy (generic, write once)

# amplifier_lite/ipc/tool_client.py
import asyncio, json, subprocess

class RemoteTool:
    """Looks like a Tool to the host, delegates over IPC."""

    def __init__(self, process, reader):
        self._proc = process
        self._reader = reader
        self._id = 0
        self.name = ""
        self.description = ""
        self._schema = {}

    async def _call(self, method, params=None):
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        self._proc.stdin.write(json.dumps(msg).encode() + b"\n")
        await self._proc.stdin.drain()
        line = await self._reader.readline()
        return json.loads(line)["result"]

    async def discover(self):
        info = await self._call("describe")
        self.name = info["name"]
        self.description = info["description"]
        self._schema = info["input_schema"]

    @property
    def input_schema(self):
        return self._schema

    async def execute(self, input):
        result = await self._call("execute", input)
        return ToolResult.model_validate(result)

    @classmethod
    async def spawn(cls, command: list[str]):
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        reader = asyncio.StreamReader()
        await asyncio.get_event_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), proc.stdout
        )
        client = cls(proc, reader)
        await client.discover()
        return client
5. Host uses it like any other tool

bash = await RemoteTool.spawn(["python", "-m", "amplifier_foundation.tools.bash.server"])

# This is indistinguishable from a local BashTool:
bash.name          # "bash"
bash.input_schema  # {...}
await bash.execute({"command": "ls"})  # ToolResult(success=True, output="...")
That's it
The key observation: the existing component code doesn't change at all. BashTool stays exactly as it is. You're just wrapping it in a server harness and putting a proxy in front of it. The proxy satisfies the same Tool protocol, so the orchestrator doesn't know or care whether the tool is local or remote.

For hooks, same pattern — serve_hook(hook) exposes register and handle over JSON-RPC, RemoteHook proxies them. The generic server/client code is written once; each component just needs a 3-line entry point.

The total shared infrastructure is maybe 200-300 lines. Then it's a one-liner per component to expose it as a service.

I guess the question then would become how are these services all started and registered to the host which, presumably, would now keep a routing table that would be used when a session is kicked off.
Right, that's the real design question. A few approaches:

Simplest: config-driven, like MCP does it

The session config just lists commands to launch:


session:
  services:
    - command: ["python", "-m", "amplifier_foundation.tools.bash.server"]
    - command: ["python", "-m", "amplifier_foundation.tools.filesystem.server"]
    - command: ["python", "-m", "amplifier_foundation.hooks.approval.server"]
    - command: ["uvx", "amplifier-skills-server"]  # from a different venv entirely
Host startup:

Spawn each subprocess
Send describe to each — they respond with what they provide (tools, hooks, whatever)
Build routing table from responses
Session runs using the table

class ServiceRegistry:
    def __init__(self):
        self.tools: dict[str, RemoteTool] = {}        # "bash" → RemoteTool
        self.hooks: dict[str, list[RemoteHook]] = {}   # "tool:pre" → [RemoteHook, ...]
    
    async def start(self, service_configs: list[ServiceConfig]):
        for config in service_configs:
            proc = await spawn(config.command)
            capabilities = await proc.describe()
            
            if capabilities["type"] == "tool":
                tool = RemoteTool(proc)
                self.tools[tool.name] = tool
            elif capabilities["type"] == "hook":
                hook = RemoteHook(proc)
                for event in hook.events:
                    self.hooks.setdefault(event, []).append(hook)
The orchestrator just uses registry.tools and registry.hooks instead of locally instantiated objects. Same interfaces, different backing.

Slightly smarter: entry-point discovery

Instead of listing commands in YAML, packages register service entry points:


# amplifier-foundation's pyproject.toml
[project.entry-points."amplifier.services"]
bash = "amplifier_foundation.tools.bash.server"
filesystem = "amplifier_foundation.tools.filesystem.server"
approval = "amplifier_foundation.hooks.approval.server"
Then the host discovers what's available in the current venv:


from importlib.metadata import entry_points

available = entry_points(group="amplifier.services")
# {'bash': EntryPoint(...), 'filesystem': EntryPoint(...), ...}
And the user's YAML becomes just a selection + config override:


session:
  services:
    - bash:
        timeout: 60
    - filesystem
    - approval
Host resolves names to entry points, spawns them, negotiates capabilities, builds the routing table.

The lifecycle looks like:


Install time:        pip install amplifier-foundation amplifier-skills
                     → entry points registered in venv

Session startup:     Host reads YAML → ["bash", "filesystem", "approval", "skills"]
                     → resolves entry points
                     → spawns 4 subprocesses
                     → describe/negotiate with each
                     → routing table built

Runtime:             LLM says "call bash"
                     → orchestrator looks up registry.tools["bash"]
                     → JSON-RPC call to bash subprocess
                     → result back

Session shutdown:    → SIGTERM to all subprocesses
The YAML stays as the user-facing "pick what you want" config. Entry points handle discovery. IPC handles isolation. No dynamic class loading, no import_and_create(), no constructor introspection. Each service is just a Python module with a __main__ that serves one or more components.

The question that follows from this: do you want one process per component (50 processes), or do you group them — say, one "foundation" service that exposes all 14 tools and 10 hooks together? Grouping reduces process count but re-couples things. Individual processes maximize isolation but you're managing a lot of subprocesses.

wouldn't this approach have version conflicts if they're using the single venv?
Yes. If everything is installed into one venv via entry points, you're back to foundation's problem — conflicting dependencies resolved by pip at install time, last writer wins.

The isolation only kicks in if services run from their own venvs. Which means the launch command needs to know which venv to use:


session:
  services:
    - bash:
        timeout: 60
    # These come from the current venv, no conflict possible
    - filesystem
    - approval
    # This comes from a separate venv
    - skills:
        venv: ~/.amplifier/envs/skills
Or more likely, the Engine manages this — each environment definition specifies which packages go in which venvs, and the spawn command just uses the right Python:


# spawning from a specific venv
proc = await spawn(["~/.amplifier/envs/skills/bin/python", "-m", "amplifier_skills.server"])

# spawning from current venv
proc = await spawn(["python", "-m", "amplifier_foundation.tools.bash.server"])
But now you're back to needing something that manages venv creation and package installation per environment — which is what the Engine already does. The difference is that instead of running one whole session per venv, you're running individual services from different venvs, all talking to one host.

That's actually more flexible: foundation tools and hooks run from the foundation venv, skills run from the skills venv, a custom tool you wrote runs from your own venv — all composing into one session, no conflicts.

The cost is you need to manage N venvs instead of 1. But uv makes venv creation fast (~200ms), and you'd only rebuild them when dependencies change.

So the full picture becomes:


Engine config:
  environments:
    foundation:
      packages: [amplifier-foundation]
    skills:
      packages: [amplifier-skills]
    my-custom:
      packages: [./my-tools]

Session config:
  services:
    # from foundation env
    - env: foundation
      services: [bash, filesystem, read, write, approval, logging]
    # from skills env
    - env: skills
      services: [skills]
    # from custom env
    - env: my-custom
      services: [my-special-tool]
Host spawns each service using the right venv's Python, connects over stdio, builds the routing table. Full dependency isolation, YAML configuration, no dynamic class loading.

What if we were to just `uv tool install` every package?
That's the cleanest version yet. uv tool install gives you per-package isolated venvs for free — no Engine, no environment management code, no venv lifecycle to maintain.

Each package registers a console script:


# amplifier-foundation's pyproject.toml
[project.scripts]
amplifier-foundation-serve = "amplifier_foundation.server:main"

# amplifier-skills' pyproject.toml
[project.scripts]
amplifier-skills-serve = "amplifier_skills.server:main"
Install:


uv tool install amplifier-foundation
uv tool install amplifier-skills
uv tool install my-custom-tools
Each gets its own isolated venv, managed entirely by uv. The commands land on PATH.

Session config:


session:
  services:
    - amplifier-foundation-serve:
        components: [bash, filesystem, read, write, approval, logging]
    - amplifier-skills-serve:
        components: [skills]
Host just spawns commands by name:


proc = await spawn(["amplifier-foundation-serve"])
proc = await spawn(["amplifier-skills-serve"])
No venv paths. No environment config. No Engine managing installs. uv did all of it already. The host doesn't even need to know where the venvs are.

This eliminates:

The Engine's venv management code
The environments.yaml config
Per-environment creation/rebuild logic
The import_and_create() machinery
ModuleRef / class path resolution
The @namespace:path system
The entire stack between "user wants a component" and "component is running" becomes: uv tool install + spawn the command + JSON-RPC negotiate. Standard Unix process model, standard Python packaging, zero custom infrastructure.

It feels like it might get tricky around the orchestrator, though.
Right. The orchestrator is the thing that coordinates all the services — it calls the provider, dispatches tool calls to tool services, emits events to hook services, manages context. If you externalize it too, the host becomes an empty shell that just spawns processes and relays messages. At that point, what is the host?

I think this is where the conversation has been leading all along. The orchestrator (and context manager, and provider calling) is the host. It's not a pluggable component — it's the core library.


┌─────────────────────────────────────────────┐
│  Host (amplifier-lite core)                 │
│                                             │
│  ┌───────────────┐  ┌───────────────────┐   │
│  │ Orchestrator  │  │ Context Manager   │   │
│  │ (built-in)    │  │ (built-in)        │   │
│  └───────┬───────┘  └───────────────────┘   │
│          │                                  │
│  ┌───────┴───────┐                          │
│  │ Provider call │ (direct HTTP, no IPC)    │
│  └───────┬───────┘                          │
│          │                                  │
│  ┌───────┴────────────────────────┐         │
│  │ Service Registry / Router      │         │
│  └──┬──────────┬──────────┬───────┘         │
└─────┼──────────┼──────────┼─────────────────┘
      │ stdio    │ stdio    │ stdio
      ▼          ▼          ▼
   ┌──────┐  ┌──────┐  ┌──────┐
   │Tools │  │Hooks │  │More  │
   │server│  │server│  │tools │
   └──────┘  └──────┘  └──────┘
There's exactly 1 orchestrator and 1 context manager. Nobody swaps them. They're tightly coupled to each other and to the hook dispatch/tool dispatch flow. Making them services would just be adding IPC to internal function calls.

The one thing you'd lose is the ability to swap in a different orchestrator via config. But you have one, and the meaningful variations (different retry strategies, different compaction approaches) are configuration, not different implementations.

So maybe the "tricky" part isn't actually tricky — it's the architecture telling you where the boundary is. The orchestrator isn't a service. It's the thing that uses services.

But it is a plugin because we will have multiple orchestrators and multiple context managers and multiple providers. When we ask amplifier-lite to run a session with a particular config, it might use any of those.
You're right — I was conflating "one per session" with "baked in." They're pluggable, just not composable. You pick one orchestrator, one context manager, one provider per session.

But that creates a real architectural tension. The orchestrator is both a plugin (swappable per session) and the coordinator (the thing that talks to all the other services). If it's an external service, how does it reach the tool and hook services?

Option A: Orchestrator runs in-process, tools/hooks are services

The host dynamically loads the orchestrator (and context manager, provider) into its own process, and they talk to external tool/hook services via the registry. You'd still need something like import_and_create() for these three components, but only these three.


amplifier-lite (host process)
├── Orchestrator (loaded in-process, swappable)
├── ContextManager (loaded in-process, swappable)
├── Provider (loaded in-process, swappable)
└── ServiceRegistry
    ├── tools → IPC to service processes
    └── hooks → IPC to service processes
Pragmatic. But it's a hybrid — two loading mechanisms.

Option B: Orchestrator IS the main process

Each orchestrator package is a standalone executable. amplifier-lite is just a thin launcher that picks which orchestrator to run based on the config and passes it the rest.


uv tool install amplifier-orchestrator-streaming
uv tool install amplifier-tools-foundation
uv tool install amplifier-skills

# amplifier-lite just figures out which orchestrator to launch
amplifier-lite run session.yaml
# → spawns: amplifier-orchestrator-streaming --services "bash,filesystem,skills" ...
# → the orchestrator spawns tool/hook services itself
Clean, but now every orchestrator package needs to embed the service-spawning and IPC infrastructure. Or it imports amplifier-lite as a library for that.

Option C: Host proxies everything

Orchestrator is a service. Tools and hooks are services. The host sits in the middle and routes all IPC. Orchestrator says "call tool bash" → host relays to bash service → result back through host to orchestrator.


Tool services ←→ Host (router) ←→ Orchestrator service
                    ↕
              Hook services
Fully uniform — everything is a service. But double IPC hop on every call, and the host is now a message bus.

The tension is real. The orchestrator needs to be pluggable but also needs tight access to the service registry. I think Option A is the most honest — the orchestrator, context manager, and provider are in-process plugins (loaded dynamically, yes, but just these three), while tools and hooks are external services. The dynamic loading is minimal and justified: you're loading the brain of the system, not 50 leaf components.

What's your instinct?

Can IPC stream?
Yes. Stdio is a byte stream — you can send as many newline-delimited JSON messages as you want. Streaming is just multiple messages for one logical request:


# Server sends chunks as they arrive
{"id": 1, "chunk": {"type": "text", "text": "Hello"}}
{"id": 1, "chunk": {"type": "text", "text": " world"}}
{"id": 1, "chunk": {"type": "tool_call", "name": "bash", "arguments": {"command": "ls"}}}
{"id": 1, "done": true, "result": {"content": "Hello world", "tool_calls": [...]}}
JSON-RPC even has a built-in concept for this — notifications (messages with no id that don't expect a response). So a streaming tool or orchestrator could emit progress notifications followed by a final response.

MCP does exactly this for long-running tool calls — it defines notifications/progress messages with a progress token that ties them back to the original request.

So streaming doesn't change the picture. An orchestrator-as-service could stream content blocks, thinking blocks, and tool calls back to the host over stdio just as easily as it returns them in-process today. The host relays them to the UI.

so then amplifier-lite-cli would just call the amplifier-lite command which would in turn call an orchestrator to get everything going? No need for a service?
Right. The orchestrator doesn't need to be a service — it just needs to be a swappable executable.


amplifier-lite-cli (UI layer)
    → amplifier-lite run session.yaml (host/launcher)
        → spawns the orchestrator command from config
            → orchestrator spawns tool/hook services
            → orchestrator calls provider directly (HTTP)
            → orchestrator manages context in-process
            → orchestrator streams results back over stdio
The orchestrator is just another uv tool install'd package with its own entry point:


uv tool install amplifier-orchestrator-streaming
uv tool install amplifier-orchestrator-planner
uv tool install amplifier-tools-foundation
Session config:


session:
  orchestrator: amplifier-orchestrator-streaming
  context_manager: simple  # flag/config, not a separate service
  provider: anthropic
  services:
    - amplifier-tools-foundation:
        components: [bash, filesystem, approval, logging]
    - amplifier-skills-serve:
        components: [skills]
amplifier-lite reads the config, spawns the orchestrator, pipes the session config to it over stdin, and relays its streaming output back to the CLI. The orchestrator spawns its own tool/hook services, talks to the LLM directly, manages context internally.

No service registration for the orchestrator. No IPC proxy layer. No double hop. It's just: CLI launches host, host launches orchestrator, orchestrator launches services. Each layer is a process that talks stdio to the layer below it.

Context manager and provider stay in-process with the orchestrator since they're tightly coupled to the agent loop. Different orchestrator packages can bundle different context management strategies or make it configurable via the config passed in.

The entire amplifier-lite host becomes very thin — read config, spawn orchestrator, relay I/O. Maybe 100 lines.

Should I just skip all this and go straight to grpc?
Probably not. The communication pattern here is simple:

describe() → capabilities
execute(input) → result (maybe streaming)
handle_event(event, data) → hook result
That's 3 methods. gRPC gives you protobuf schemas, code generation, bidirectional streaming, HTTP/2 — but it also means proto files, a compilation step, a grpc dependency in every service package, and more complex process management (port allocation instead of stdio pipes).

gRPC is worth it when you have many teams building services independently and need strict contract enforcement across language boundaries. Here you control all the services, they're all Python, and the protocol fits in a page.

Newline-delimited JSON over stdio gets you:

Zero dependency (just json stdlib)
Process lifecycle for free (parent spawns child, pipe is the connection, SIGTERM is shutdown)
Streaming (multiple lines)
MCP compatibility if you ever want it
Dead simple debugging (echo '{"method":"describe"}' | python -m my_service)
If you later find stdio JSON limiting, gRPC is a well-understood upgrade path. But I'd start with the simplest thing that works and see if you actually hit its limits