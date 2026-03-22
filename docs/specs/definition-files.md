# Definition Files Spec

Definition files are YAML files that declare agents and behaviors in the Amplifier IPC system. An **agent** is the top-level unit of composition — it names an orchestrator, context manager, provider, and a tree of behaviors. A **behavior** is a unit of capability (tools, hooks, context) backed by an optional service. Agents compose behaviors; behaviors can compose other behaviors recursively.

This document is the authoritative reference for definition file formats, identity, namespacing, service lifecycle, and local development overrides.

---

## Agent Definition Schema

An agent definition uses `agent:` as the top-level YAML key.

```yaml
agent:
  ref: amplifier-dev
  uuid: 52d19e87-24ba-4291-a872-69d963b96ce9
  version: 1
  description: Amplifier development agent with full foundation capabilities

  orchestrator: streaming
  context_manager: simple
  provider: providers:anthropic

  tools: true
  hooks: true
  agents: true
  context: true

  behaviors:
    - modes: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-modes/behaviors/modes.yaml
    - skills: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-skills/behaviors/skills.yaml
    - routing: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-routing-matrix/behaviors/routing.yaml

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-foundation
    command: amplifier-foundation-serve
```

### Agent-only fields

- **`orchestrator`** — Component reference for the orchestrator. Controls conversation flow.
- **`context_manager`** — Component reference for the context manager. Controls system prompt assembly.
- **`provider`** — Component reference for the LLM provider.
- **`agents`** — Boolean. Whether this agent contributes sub-agent capabilities from its own service.

See [Component Reference Syntax](#component-reference-syntax) for how these references resolve.

---

## Behavior Definition Schema

A behavior definition uses `behavior:` as the top-level YAML key.

```yaml
behavior:
  ref: modes
  uuid: 6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139
  version: 1
  description: Generic mode system for runtime behavior modification

  tools: true
  hooks: true
  context: true

  behaviors: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-modes
    command: amplifier-modes-serve
```

Behaviors may compose other behaviors by listing them in `behaviors:`, using the same `{alias: url}` dict format as agents. This is recursive — a behavior's sub-behaviors can themselves have sub-behaviors.

Content-only behaviors that provide no runtime service omit the `service:` block entirely. Their content is discovered statically or served by the parent agent's service.

---

## Identity and Namespacing

### Definition identity

Every definition (agent or behavior) has two identity fields:

- **`ref`** — A short, human-readable name (e.g., `modes`, `amplifier-dev`).
- **`uuid`** — A globally unique identifier (UUID v4).

From these, a `definition_id` is computed:

```
<type>_<ref>_<uuid>
```

Examples:

```
agent_amplifier-dev_52d19e87-24ba-4291-a872-69d963b96ce9
behavior_modes_6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139
```

The `definition_id` determines storage paths:

| Artifact | Path |
|---|---|
| Cached definition | `$AMPLIFIER_HOME/definitions/<definition_id>.yaml` |
| Service environment | `$AMPLIFIER_HOME/environments/<definition_id>/` |

### Alias files

Global alias files map human-readable names to definition IDs:

```yaml
# $AMPLIFIER_HOME/agents.yaml
foundation: agent_foundation_3898a638-71de-427a-8183-b80eba8b26be
amplifier-dev: agent_amplifier-dev_52d19e87-24ba-4291-a872-69d963b96ce9
```

```yaml
# $AMPLIFIER_HOME/behaviors.yaml
modes: behavior_modes_6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139
skills: behavior_skills_6108ceb2-3fbb-4ac3-aa5d-2e1d2dcaabce
```

### Agent-scoped namespacing

When an agent is registered, its entire dependency tree is resolved. Each behavior in the tree gets an **alias** — the dict key from the `behaviors:` list entry that included it. This alias is scoped to the agent's namespace (identified by the agent's UUID).

Key properties:

- Alias uniqueness is enforced within a single agent's resolved tree. Registration fails on collision.
- Two different agents can each include a behavior with the same `ref` without conflict, because each agent has its own namespace.
- At runtime, the host identifies running services by their alias, scoped to the agent session.

---

## Component Reference Syntax

Component references use the format `<ref>:<component_name>` to identify a named component from a specific service.

```yaml
agent:
  ref: foundation
  orchestrator: streaming              # shorthand for foundation:streaming
  context_manager: simple              # shorthand for foundation:simple
  provider: providers:anthropic        # explicit: providers service's anthropic component
```

**Rules:**

- A bare `<component_name>` (no colon) is shorthand for `<this_ref>:<component_name>` — it references a component from this definition's own service.
- An explicit `<ref>:<component_name>` references a component from the service identified by `<ref>`.
- `ref` values are unique within the agent's namespace (enforced at registration), so references are unambiguous.

---

## The Service Block

The `service:` block (singular) declares how to install and run the backing service process.

```yaml
service:
  stack: uv
  source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-modes
  command: amplifier-modes-serve
```

| Field | Description |
|---|---|
| `stack` | Language toolchain. Determines how the environment is created and dependencies installed. Values: `uv`, `cargo`, `npm`, etc. |
| `source` | Where to get the code. Uses `git+` URLs for production. Pip-installable specifier for the `uv` stack. |
| `command` | The executable to run to start the service process. The host runs this in the installed environment. |

### Install lifecycle (`uv` stack)

```bash
ENVIRONMENT=$AMPLIFIER_HOME/environments/<definition_id>
uv venv $ENVIRONMENT
uv pip install --python $ENVIRONMENT/bin/python <source>
```

### Run lifecycle

```bash
uv run --venv $ENVIRONMENT <command>
```

### Content-only definitions

Definitions that provide only context or content files and no runtime service omit the `service:` block entirely.

---

## Component Configuration

The `config:` block declares configuration for service components. It lives at the same level as `tools:`, `hooks:`, and other fields inside a definition. Keys are component names, optionally prefixed with `<ref>:` to target included behaviors' components.

### Behavior-level config (defaults for own components)

```yaml
behavior:
  ref: modes
  tools: true
  hooks: true
  config:
    mode-tool:
      gate_policy: warn
    mode-hooks:
      search_paths: []
```

A behavior's `config:` block sets default values for its own service's components. The keys are bare component names (shorthand for `<this_ref>:<component_name>`).

### Agent-level config (own components + behavior overrides)

```yaml
agent:
  ref: amplifier-dev
  behaviors:
    - modes: https://...

  config:
    # Own service components (bare name = this ref's service)
    streaming:
      max_iterations: 50
    bash:
      timeout: 60
    # Override an included behavior's component config
    modes:mode-tool:
      gate_policy: block
    modes:mode-hooks:
      search_paths: ['@superpowers:modes']
```

An agent's `config:` block can configure its own components AND override config from included behaviors. Use the `<ref>:<component_name>` syntax to target a specific behavior's component.

### Resolution order

Outer definitions override inner definitions:

1. **Agent `config:`** (highest priority)
2. **Behavior `config:`** (defaults)
3. **Component defaults** (hardcoded in the component class)

If a behavior sets `gate_policy: warn` and the agent sets `modes:mode-tool: {gate_policy: block}`, the component receives `block`.

### Config delivery to services

Configuration is delivered to service processes during startup, after the `describe` handshake:

1. **`scan_package()`** discovers component classes but does NOT instantiate them
2. **`describe`** reports capabilities from class metadata (decorators set component type, name, events, etc. on the class)
3. **Host sends `configure`** with the merged config for that service's components:
   ```json
   {
     "method": "configure",
     "params": {
       "config": {
         "mode-tool": {"gate_policy": "block"},
         "mode-hooks": {"search_paths": ["@superpowers:modes"]}
       }
     }
   }
   ```
4. **Server instantiates components** with their config: `instance = cls(config={"gate_policy": "block"})` or `instance = cls()` for components with no config
5. Components are ready for use

The startup sequence is: **spawn → describe → configure → ready**

### All config is static

Component configuration is set once at session startup. It does not change per-call. All existing config values fall into these categories:

| Category | Examples |
|---|---|
| Feature toggles | `enabled: true`, `show_thinking_stream: true` |
| Path templates | `session_log_template: ~/.amplifier/projects/{project}/sessions/{session_id}/events.jsonl` |
| Numeric thresholds | `read_threshold: 30`, `max_turns: 10`, `timeout: 60` |
| Plugin/extension lists | `skills: [git+https://github.com/...]` |
| Exclusion/allow lists | `exclude_tools: [tool-delegate]`, `allowlist: [session_id, turn_id]` |
| Named presets | `default_matrix: balanced`, `gate_policy: warn`, `engine: native` |
| Injection roles | `inject_role: user` |

---

## Local Development Overrides

Definitions use `git+` URLs for production sources. For local development, use settings file overrides instead of modifying definitions.

### Override configuration

```yaml
# .amplifier/settings.yaml (project-level)
amplifier_ipc:
  service_overrides:
    amplifier-dev:              # agent alias
      modes:                    # behavior alias within that agent
        command: ["uv", "run", "--directory", "./services/amplifier-modes", "amplifier-modes-serve"]
        working_dir: ./services/amplifier-modes
      foundation:
        command: ["uv", "run", "--directory", "./services/amplifier-foundation", "amplifier-foundation-serve"]
        working_dir: ./services/amplifier-foundation
```

### Override resolution order

Highest to lowest priority:

1. **Project-level** — `.amplifier/settings.yaml`
2. **User-level** — `~/.amplifier/settings.yaml`
3. **Definition's `service:` block** — installed venv + command
4. **Bare command on `$PATH`** — fallback

### Why `command`, not `source`

The `command` override with `uv run --directory` executes directly from the local source tree. Code changes are immediately reflected without reinstalling. Overriding `source` with a local path would install the package into the venv (not editable), requiring a reinstall on every change.

---

## Discovery and Registration

### Discovery

```bash
amplifier-ipc discover <location>
```

Recursively scans YAML files. Files with `agent:` or `behavior:` as the top-level key are recognized as definitions.

### Registration

```bash
amplifier-ipc discover <location> --register
```

Caches definitions to `$AMPLIFIER_HOME/definitions/` and creates alias entries in `agents.yaml` or `behaviors.yaml`. When registering an agent, the entire behavior tree is walked — each behavior URL is fetched, cached, and aliased within the agent's namespace.

### Installation

```bash
amplifier-ipc install <agent_name>
```

Creates service environments for each definition in the agent's tree that has a `service:` block.

### Run

```bash
amplifier-ipc run --agent <agent_name> [message]
```

Resolves the agent, walks its behavior tree, collects all services, spawns service processes, builds the capability registry, assembles the system prompt, and sends the user message to the orchestrator.

### Full lifecycle

```bash
amplifier-ipc discover services/ --register    # scan and register definitions
amplifier-ipc install amplifier-dev            # create service environments
amplifier-ipc run --agent amplifier-dev "hello" # run the agent
```

### Cleanup

```bash
amplifier-ipc unregister <name>                # remove a definition + environment
amplifier-ipc uninstall <name>                 # remove just the environment
amplifier-ipc reset --remove definitions       # remove all definitions + aliases
amplifier-ipc reset --remove all               # remove everything
```

---

## Field Reference

### All fields

| Field | Type | Required | Agent | Behavior | Description |
|---|---|---|---|---|---|
| `ref` | string | **yes** | yes | yes | Short human-readable name |
| `uuid` | UUID v4 | **yes** | yes | yes | Globally unique identifier |
| `version` | int | no | yes | yes | Definition version number |
| `description` | string | no | yes | yes | Human-readable description |
| `orchestrator` | component ref | no | yes | no | Conversation flow controller |
| `context_manager` | component ref | no | yes | no | System prompt assembler |
| `provider` | component ref | no | yes | no | LLM provider |
| `tools` | bool | no | yes | yes | Contributes tools from own service |
| `hooks` | bool | no | yes | yes | Contributes hooks from own service |
| `agents` | bool | no | yes | no | Contributes sub-agents from own service |
| `context` | bool | no | yes | yes | Contributes context from own service |
| `behaviors` | list of `{alias: url}` | no | yes | yes | Composed behaviors |
| `config` | object | no | yes | yes | Per-component configuration (see [Component Configuration](#component-configuration)) |
| `service` | object | no | yes | yes | Service install/run configuration |
| `service.stack` | string | if `service` | yes | yes | Language toolchain (`uv`, `cargo`, `npm`) |
| `service.source` | string | if `service` | yes | yes | Package source (`git+` URL) |
| `service.command` | string | if `service` | yes | yes | Command to start the service process |

### Top-level key

| Key | Meaning |
|---|---|
| `agent:` | This file defines an agent |
| `behavior:` | This file defines a behavior |

### Computed identity

| Value | Formula |
|---|---|
| `definition_id` | `<type>_<ref>_<uuid>` |
| Cached path | `$AMPLIFIER_HOME/definitions/<definition_id>.yaml` |
| Environment path | `$AMPLIFIER_HOME/environments/<definition_id>/` |
