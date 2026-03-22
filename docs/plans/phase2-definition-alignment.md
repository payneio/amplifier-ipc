# Phase 2: Definition File Alignment Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Rewrite all agent and behavior YAML definition files to match the spec in `docs/specs/definition-files.md`, delete obsolete `*-ipc.yaml` files, create the local dev settings file, and write a comprehensive definition-validation test suite. Behaviors that had component configuration in the old format must include `config:` blocks with component names as keys in the new format.

**Architecture:** Every definition file must use the new nested format: `agent:` or `behavior:` as the top-level YAML key, `ref` (not `local_ref`), `uuid` (UUID v4), and singular `service:` with `stack`/`source`/`command` (only for behaviors backed by a separate service process). Content-only behaviors omit `service:` entirely. Foundation behaviors also omit `service:` because they are served by the agent's own foundation service. All `source` fields use `git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/<service-name>`.

**Tech Stack:** YAML, Python 3.11+, pytest

**Prerequisite:** Phase 1 (parser alignment) must be complete. The parsers must already read the new nested format.

---

## Service Architecture Reference

Before rewriting files, you need to understand which behaviors need `service:` blocks.

**Services with their own process** (behavior YAML needs `service:` block):

| Service | Binary | Source subdirectory |
|---------|--------|---------------------|
| amplifier-modes | `amplifier-modes-serve` | `/services/amplifier-modes` |
| amplifier-skills | `amplifier-skills-serve` | `/services/amplifier-skills` |
| amplifier-routing-matrix | `amplifier-routing-matrix-serve` | `/services/amplifier-routing-matrix` |
| amplifier-superpowers | `amplifier-superpowers-serve` | `/services/amplifier-superpowers` |
| amplifier-recipes | `amplifier-recipes-serve` | `/services/amplifier-recipes` |
| amplifier-filesystem | `amplifier-filesystem-serve` | `/services/amplifier-filesystem` |
| amplifier-providers | `amplifier-providers-serve` | `/services/amplifier-providers` |
| amplifier-foundation | `amplifier-foundation-serve` | `/services/amplifier-foundation` |
| amplifier-amplifier | `amplifier-amplifier-serve` | `/services/amplifier-amplifier` |
| amplifier-core | `amplifier-core-serve` | `/services/amplifier-core` |
| amplifier-design-intelligence | `amplifier-design-intelligence-serve` | `/services/amplifier-design-intelligence` |
| amplifier-browser-tester | `amplifier-browser-tester-serve` | `/services/amplifier-browser-tester` |

**Foundation behaviors** (in `services/amplifier-foundation/behaviors/`) — these provide capabilities FROM the foundation service process. They do NOT need their own `service:` block because the agent definition already declares the foundation service. The foundation service process hosts all of these capabilities.

**Content-serving behaviors** — these have their own service package with `[project.scripts]` entries that serve content files (context, agent declarations). They DO get `service:` blocks pointing to their own service binary.

The determination for each behavior is noted in the task where it is rewritten.

---

## UUID Generation

Many files below show `<generate-fresh-uuid>` as a placeholder. During implementation, generate real UUIDs with:

```bash
python3 -c "import uuid; print(uuid.uuid4())"
```

Run this once per file that needs a new UUID. Existing UUIDs (like `6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139` for modes) should be preserved — only generate new ones for files that didn't have UUIDs before or where the identity is changing.

---

### Task 1: Delete obsolete `*-ipc.yaml` files

**Files:**
- Delete: `services/amplifier-modes/behaviors/modes-ipc.yaml`
- Delete: `services/amplifier-skills/behaviors/skills-ipc.yaml`
- Delete: `services/amplifier-routing-matrix/behaviors/routing-ipc.yaml`
- Delete: `services/amplifier-foundation/behaviors/foundation-ipc.yaml`
- Delete: `services/amplifier-providers/behaviors/providers-ipc.yaml`

These were the old flat-format IPC definitions. They have been superseded by the rewritten non-`-ipc` files.

**Step 1: Delete all five files**

```bash
cd /data/labs/amplifier-ipc && rm \
  services/amplifier-modes/behaviors/modes-ipc.yaml \
  services/amplifier-skills/behaviors/skills-ipc.yaml \
  services/amplifier-routing-matrix/behaviors/routing-ipc.yaml \
  services/amplifier-foundation/behaviors/foundation-ipc.yaml \
  services/amplifier-providers/behaviors/providers-ipc.yaml
```

**Step 2: Verify they're gone**

```bash
cd /data/labs/amplifier-ipc && ls services/*/behaviors/*-ipc.yaml 2>&1
```
Expected: `No such file or directory` (no matches).

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add -A && git commit -m "chore: delete obsolete *-ipc.yaml definition files"
```

---

### Task 2: Rewrite external service behavior definitions (modes, skills, routing)

**Files:**
- Modify: `services/amplifier-modes/behaviors/modes.yaml`
- Modify: `services/amplifier-skills/behaviors/skills.yaml`
- Modify: `services/amplifier-skills/behaviors/skills-tool.yaml`
- Modify: `services/amplifier-routing-matrix/behaviors/routing.yaml`

These behaviors are backed by their own separate service process. Each needs a `service:` block.

**Step 1: Rewrite `modes.yaml`**

Replace the entire content of `services/amplifier-modes/behaviors/modes.yaml` with:

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

**Step 2: Rewrite `skills.yaml`**

Replace `services/amplifier-skills/behaviors/skills.yaml` with:

```yaml
behavior:
  ref: skills
  uuid: 6108ceb2-3fbb-4ac3-aa5d-2e1d2dcaabce
  version: 1
  description: Full skills support with skill loading tool and content

  tools: true
  context: true

  behaviors: []

  config:
    skills-tool:
      skills: []
      visibility: full

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-skills
    command: amplifier-skills-serve
```

**Step 3: Rewrite `skills-tool.yaml`**

Replace `services/amplifier-skills/behaviors/skills-tool.yaml` with:

```yaml
behavior:
  ref: skills-tool
  uuid: <generate-fresh-uuid>
  version: 1
  description: Minimal skills support — just the tool-skills module and context instructions

  tools: true
  context: true

  behaviors: []

  config:
    skills-tool:
      visibility: minimal

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-skills
    command: amplifier-skills-serve
```

Note: `skills-tool` shares the same service package as `skills` but is a separate behavior with its own UUID. Generate a fresh UUID for it.

**Step 4: Rewrite `routing.yaml`**

Replace `services/amplifier-routing-matrix/behaviors/routing.yaml` with:

```yaml
behavior:
  ref: routing
  uuid: 754ff88c-34ea-4e5b-8da6-d7bbbc80682e
  version: 1
  description: Model routing via routing matrix hooks and content

  hooks: true
  context: true

  behaviors: []

  config:
    routing-hook:
      default_matrix: balanced

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-routing-matrix
    command: amplifier-routing-matrix-serve
```

**Step 5: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
for f in [
    'services/amplifier-modes/behaviors/modes.yaml',
    'services/amplifier-skills/behaviors/skills.yaml',
    'services/amplifier-skills/behaviors/skills-tool.yaml',
    'services/amplifier-routing-matrix/behaviors/routing.yaml',
]:
    data = yaml.safe_load(open(f))
    inner = data.get('behavior', {})
    assert inner.get('ref'), f'{f}: missing ref'
    assert inner.get('uuid'), f'{f}: missing uuid'
    assert inner.get('service', {}).get('command'), f'{f}: missing service.command'
    print(f'{f}: OK ({inner[\"ref\"]})')
"
```
Expected: All four print `OK`.

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-modes/behaviors/modes.yaml services/amplifier-skills/behaviors/skills.yaml services/amplifier-skills/behaviors/skills-tool.yaml services/amplifier-routing-matrix/behaviors/routing.yaml && git commit -m "feat: rewrite modes, skills, skills-tool, routing behaviors to spec format"
```

---

### Task 3: Rewrite other external service behavior definitions

**Files:**
- Modify: `services/amplifier-superpowers/behaviors/superpowers-methodology.yaml`
- Modify: `services/amplifier-recipes/behaviors/recipes.yaml`
- Modify: `services/amplifier-filesystem/behaviors/apply-patch.yaml`

These behaviors are backed by their own separate service processes.

**Step 1: Rewrite `superpowers-methodology.yaml`**

Replace `services/amplifier-superpowers/behaviors/superpowers-methodology.yaml` with:

```yaml
behavior:
  ref: superpowers-methodology
  uuid: <generate-fresh-uuid>
  version: 1
  description: TDD and subagent-driven development methodology with specialized agents, interactive modes, and a skills library

  tools: true
  hooks: true
  context: true

  behaviors: []

  config:
    mode-tool:
      gate_policy: warn
    mode-hooks:
      search_paths: []
    skills-tool:
      skills: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-superpowers
    command: amplifier-superpowers-serve
```

**Step 2: Rewrite `recipes.yaml`**

Replace `services/amplifier-recipes/behaviors/recipes.yaml` with:

```yaml
behavior:
  ref: recipes
  uuid: <generate-fresh-uuid>
  version: 1
  description: Multi-step AI agent orchestration via declarative YAML recipes

  tools: true
  context: true

  behaviors: []

  config:
    recipes-tool:
      session_dir: ~/.amplifier/recipe-sessions
      cleanup: true

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-recipes
    command: amplifier-recipes-serve
```

**Step 3: Rewrite `apply-patch.yaml`**

Replace `services/amplifier-filesystem/behaviors/apply-patch.yaml` with:

```yaml
behavior:
  ref: apply-patch
  uuid: <generate-fresh-uuid>
  version: 1
  description: V4A diff-based file editing via apply_patch tool

  tools: true
  context: true

  behaviors: []

  config:
    apply-patch-tool:
      engine: native
      allowed_paths: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-filesystem
    command: amplifier-filesystem-serve
```

**Step 4: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
for f in [
    'services/amplifier-superpowers/behaviors/superpowers-methodology.yaml',
    'services/amplifier-recipes/behaviors/recipes.yaml',
    'services/amplifier-filesystem/behaviors/apply-patch.yaml',
]:
    data = yaml.safe_load(open(f))
    inner = data.get('behavior', {})
    assert inner.get('ref'), f'{f}: missing ref'
    assert inner.get('uuid'), f'{f}: missing uuid'
    assert inner.get('service', {}).get('command'), f'{f}: missing service.command'
    print(f'{f}: OK ({inner[\"ref\"]})')
"
```
Expected: All three print `OK`.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-superpowers/behaviors/superpowers-methodology.yaml services/amplifier-recipes/behaviors/recipes.yaml services/amplifier-filesystem/behaviors/apply-patch.yaml && git commit -m "feat: rewrite superpowers, recipes, apply-patch behaviors to spec format"
```

---

### Task 4: Rewrite foundation behavior definitions (no service block)

**Files:**
- Modify: `services/amplifier-foundation/behaviors/agents.yaml`
- Modify: `services/amplifier-foundation/behaviors/amplifier-dev.yaml`
- Modify: `services/amplifier-foundation/behaviors/foundation-expert.yaml`
- Modify: `services/amplifier-foundation/behaviors/logging.yaml`
- Modify: `services/amplifier-foundation/behaviors/progress-monitor.yaml`
- Modify: `services/amplifier-foundation/behaviors/redaction.yaml`

These behaviors are capabilities provided BY the foundation service process. They do NOT have their own `service:` block — the agent definition already declares the foundation service.

For each file, generate a fresh UUID during implementation. All follow the same pattern:

```yaml
behavior:
  ref: <ref-name>
  uuid: <generate-fresh-uuid>
  version: 1
  description: <description>

  tools: <true if behavior provides tools>
  hooks: <true if behavior provides hooks>
  context: <true if behavior provides context>

  behaviors: []
```

**Step 1: Rewrite `agents.yaml`**

Replace `services/amplifier-foundation/behaviors/agents.yaml` with:

```yaml
behavior:
  ref: agents
  uuid: <generate-fresh-uuid>
  version: 1
  description: Agent orchestration capability with enhanced delegate tool

  tools: true
  context: true

  behaviors: []

  config:
    delegate-tool:
      features:
        parallel: true
        context_sharing: true
      settings:
        max_concurrent: 4
    skills-tool:
      skills: []
```

**Step 2: Rewrite `amplifier-dev.yaml` (the behavior, NOT the agent)**

Replace `services/amplifier-foundation/behaviors/amplifier-dev.yaml` with:

```yaml
behavior:
  ref: amplifier-dev-behavior
  uuid: <generate-fresh-uuid>
  version: 1
  description: Amplifier ecosystem development behavior — multi-repo workflows, testing patterns, and ecosystem expertise

  context: true

  behaviors: []
```

Note: The `ref` is `amplifier-dev-behavior` (not `amplifier-dev`) to avoid collision with the agent definition that has `ref: amplifier-dev`.

**Step 3: Rewrite `foundation-expert.yaml`**

Replace `services/amplifier-foundation/behaviors/foundation-expert.yaml` with:

```yaml
behavior:
  ref: foundation-expert
  uuid: <generate-fresh-uuid>
  version: 1
  description: Expert consultant for bundle composition, patterns, and building AI applications

  context: true

  behaviors: []
```

**Step 4: Rewrite `logging.yaml`**

Replace `services/amplifier-foundation/behaviors/logging.yaml` with:

```yaml
behavior:
  ref: logging
  uuid: <generate-fresh-uuid>
  version: 1
  description: Session logging to JSONL files

  hooks: true

  behaviors: []

  config:
    logging-hook:
      mode: jsonl
      template: ~/.amplifier/projects/{project}/sessions/{session_id}/events.jsonl
```

**Step 5: Rewrite `progress-monitor.yaml`**

Replace `services/amplifier-foundation/behaviors/progress-monitor.yaml` with:

```yaml
behavior:
  ref: progress-monitor
  uuid: <generate-fresh-uuid>
  version: 1
  description: Detects analysis paralysis patterns and injects corrective prompts

  hooks: true

  behaviors: []

  config:
    progress-monitor-hook:
      read_threshold: 30
      max_turns: 10
```

**Step 6: Rewrite `redaction.yaml`**

Replace `services/amplifier-foundation/behaviors/redaction.yaml` with:

```yaml
behavior:
  ref: redaction
  uuid: <generate-fresh-uuid>
  version: 1
  description: Redact secrets and PII from logs

  hooks: true

  behaviors: []

  config:
    redaction-hook:
      allowlist:
        - session_id
        - turn_id
```

**Step 7: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
for f in [
    'services/amplifier-foundation/behaviors/agents.yaml',
    'services/amplifier-foundation/behaviors/amplifier-dev.yaml',
    'services/amplifier-foundation/behaviors/foundation-expert.yaml',
    'services/amplifier-foundation/behaviors/logging.yaml',
    'services/amplifier-foundation/behaviors/progress-monitor.yaml',
    'services/amplifier-foundation/behaviors/redaction.yaml',
]:
    data = yaml.safe_load(open(f))
    inner = data.get('behavior', {})
    assert inner.get('ref'), f'{f}: missing ref'
    assert inner.get('uuid'), f'{f}: missing uuid'
    assert 'service' not in inner, f'{f}: foundation behavior should NOT have service block'
    print(f'{f}: OK ({inner[\"ref\"]})')
"
```
Expected: All six print `OK`.

**Step 8: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-foundation/behaviors/agents.yaml services/amplifier-foundation/behaviors/amplifier-dev.yaml services/amplifier-foundation/behaviors/foundation-expert.yaml services/amplifier-foundation/behaviors/logging.yaml services/amplifier-foundation/behaviors/progress-monitor.yaml services/amplifier-foundation/behaviors/redaction.yaml && git commit -m "feat: rewrite foundation behaviors (agents, amplifier-dev, foundation-expert, logging, progress-monitor, redaction) to spec format"
```

---

### Task 5: Rewrite remaining foundation behavior definitions

**Files:**
- Modify: `services/amplifier-foundation/behaviors/sessions.yaml`
- Modify: `services/amplifier-foundation/behaviors/shadow-amplifier.yaml`
- Modify: `services/amplifier-foundation/behaviors/status-context.yaml`
- Modify: `services/amplifier-foundation/behaviors/streaming-ui.yaml`
- Modify: `services/amplifier-foundation/behaviors/tasks.yaml`
- Modify: `services/amplifier-foundation/behaviors/todo-reminder.yaml`

Same pattern as Task 4: foundation behaviors, no `service:` block. Generate fresh UUIDs.

**Step 1: Rewrite `sessions.yaml`**

```yaml
behavior:
  ref: sessions
  uuid: <generate-fresh-uuid>
  version: 1
  description: Session management — naming, logging, analysis, and debugging

  hooks: true

  behaviors: []

  config:
    session-naming-hook:
      trigger: first_response
      interval: 5
```

**Step 2: Rewrite `shadow-amplifier.yaml`**

```yaml
behavior:
  ref: shadow-amplifier
  uuid: <generate-fresh-uuid>
  version: 1
  description: Amplifier ecosystem-specific shadow environment support

  context: true

  behaviors: []
```

**Step 3: Rewrite `status-context.yaml`**

```yaml
behavior:
  ref: status-context
  uuid: <generate-fresh-uuid>
  version: 1
  description: Inject environment and git status into agent context

  hooks: true

  behaviors: []

  config:
    status-context-hook:
      include_datetime: true
      include_git_status: true
```

**Step 4: Rewrite `streaming-ui.yaml`**

```yaml
behavior:
  ref: streaming-ui
  uuid: <generate-fresh-uuid>
  version: 1
  description: Streaming UI display for thinking blocks, tool calls, and token usage

  hooks: true

  behaviors: []

  config:
    streaming-ui-hook:
      show_thinking_stream: true
      show_token_usage: true
      show_tool_calls: true
```

**Step 5: Rewrite `tasks.yaml`**

```yaml
behavior:
  ref: tasks
  uuid: <generate-fresh-uuid>
  version: 1
  description: Legacy task tool behavior for backwards compatibility

  tools: true
  context: true

  behaviors: []

  config:
    task-tool:
      exclude_tools:
        - tool-delegate
```

**Step 6: Rewrite `todo-reminder.yaml`**

```yaml
behavior:
  ref: todo-reminder
  uuid: <generate-fresh-uuid>
  version: 1
  description: Todo tracking with automatic context reminders and visual progress display

  tools: true
  hooks: true

  behaviors: []

  config:
    todo-reminder-hook:
      inject_role: user
      priority: 90
    todo-display-hook:
      show_progress_bar: true
      show_border: true
```

**Step 7: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
for f in [
    'services/amplifier-foundation/behaviors/sessions.yaml',
    'services/amplifier-foundation/behaviors/shadow-amplifier.yaml',
    'services/amplifier-foundation/behaviors/status-context.yaml',
    'services/amplifier-foundation/behaviors/streaming-ui.yaml',
    'services/amplifier-foundation/behaviors/tasks.yaml',
    'services/amplifier-foundation/behaviors/todo-reminder.yaml',
]:
    data = yaml.safe_load(open(f))
    inner = data.get('behavior', {})
    assert inner.get('ref'), f'{f}: missing ref'
    assert inner.get('uuid'), f'{f}: missing uuid'
    assert 'service' not in inner, f'{f}: foundation behavior should NOT have service block'
    print(f'{f}: OK ({inner[\"ref\"]})')
"
```
Expected: All six print `OK`.

**Step 8: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-foundation/behaviors/sessions.yaml services/amplifier-foundation/behaviors/shadow-amplifier.yaml services/amplifier-foundation/behaviors/status-context.yaml services/amplifier-foundation/behaviors/streaming-ui.yaml services/amplifier-foundation/behaviors/tasks.yaml services/amplifier-foundation/behaviors/todo-reminder.yaml && git commit -m "feat: rewrite foundation behaviors (sessions, shadow-amplifier, status-context, streaming-ui, tasks, todo-reminder) to spec format"
```

---

### Task 6: Rewrite content-serving behavior definitions

**Files:**
- Modify: `services/amplifier-amplifier/behaviors/amplifier-expert.yaml`
- Modify: `services/amplifier-amplifier/behaviors/amplifier-dev.yaml`
- Modify: `services/amplifier-core/behaviors/core-expert.yaml`
- Modify: `services/amplifier-design-intelligence/behaviors/design-intelligence.yaml`
- Modify: `services/amplifier-browser-tester/behaviors/browser-tester.yaml`

These services have `[project.scripts]` entries and serve content files (context, agent declarations). They each have their own service process, so they DO get `service:` blocks.

**Step 1: Rewrite `amplifier-expert.yaml`**

Replace `services/amplifier-amplifier/behaviors/amplifier-expert.yaml` with:

```yaml
behavior:
  ref: amplifier-expert
  uuid: <generate-fresh-uuid>
  version: 1
  description: Authoritative consultant for the complete Amplifier ecosystem

  context: true

  behaviors: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-amplifier
    command: amplifier-amplifier-serve
```

**Step 2: Rewrite `amplifier-dev.yaml` (in amplifier-amplifier, not foundation)**

Replace `services/amplifier-amplifier/behaviors/amplifier-dev.yaml` with:

```yaml
behavior:
  ref: amplifier-dev-hygiene
  uuid: <generate-fresh-uuid>
  version: 1
  description: Development hygiene and best practices for Amplifier CLI users

  context: true

  behaviors: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-amplifier
    command: amplifier-amplifier-serve
```

Note: `ref` is `amplifier-dev-hygiene` to avoid collision with other `amplifier-dev` refs.

**Step 3: Rewrite `core-expert.yaml`**

Replace `services/amplifier-core/behaviors/core-expert.yaml` with:

```yaml
behavior:
  ref: core-expert
  uuid: <generate-fresh-uuid>
  version: 1
  description: Expert consultant for Amplifier kernel internals

  context: true

  behaviors: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-core
    command: amplifier-core-serve
```

**Step 4: Rewrite `design-intelligence.yaml`**

Replace `services/amplifier-design-intelligence/behaviors/design-intelligence.yaml` with:

```yaml
behavior:
  ref: design-intelligence
  uuid: <generate-fresh-uuid>
  version: 1
  description: Comprehensive design intelligence with specialized agents and knowledge base

  context: true

  behaviors: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-design-intelligence
    command: amplifier-design-intelligence-serve
```

**Step 5: Rewrite `browser-tester.yaml`**

Replace `services/amplifier-browser-tester/behaviors/browser-tester.yaml` with:

```yaml
behavior:
  ref: browser-tester
  uuid: <generate-fresh-uuid>
  version: 1
  description: Browser automation behavior — adds browser agents for web interaction, research, and visual documentation

  context: true

  behaviors: []

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-browser-tester
    command: amplifier-browser-tester-serve
```

**Step 6: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
for f in [
    'services/amplifier-amplifier/behaviors/amplifier-expert.yaml',
    'services/amplifier-amplifier/behaviors/amplifier-dev.yaml',
    'services/amplifier-core/behaviors/core-expert.yaml',
    'services/amplifier-design-intelligence/behaviors/design-intelligence.yaml',
    'services/amplifier-browser-tester/behaviors/browser-tester.yaml',
]:
    data = yaml.safe_load(open(f))
    inner = data.get('behavior', {})
    assert inner.get('ref'), f'{f}: missing ref'
    assert inner.get('uuid'), f'{f}: missing uuid'
    assert inner.get('service', {}).get('command'), f'{f}: missing service.command'
    print(f'{f}: OK ({inner[\"ref\"]})')
"
```
Expected: All five print `OK`.

**Step 7: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-amplifier/behaviors/ services/amplifier-core/behaviors/ services/amplifier-design-intelligence/behaviors/ services/amplifier-browser-tester/behaviors/ && git commit -m "feat: rewrite content-serving behaviors (amplifier-expert, amplifier-dev-hygiene, core-expert, design-intelligence, browser-tester) to spec format"
```

---

### Task 7: Rewrite `amplifier-dev.yaml` agent definition

**Files:**
- Modify: `services/amplifier-foundation/agents/amplifier-dev.yaml`

This is the primary development agent. It must use the full spec format with `agent:` wrapper, `ref`, `uuid`, `service:` block, and `behaviors:` list using `{alias: url}` dicts pointing to raw GitHub URLs.

**Step 1: Rewrite the file**

Replace `services/amplifier-foundation/agents/amplifier-dev.yaml` entirely with:

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

**Step 2: Verify YAML is valid and parseable**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
data = yaml.safe_load(open('services/amplifier-foundation/agents/amplifier-dev.yaml'))
inner = data['agent']
assert inner['ref'] == 'amplifier-dev'
assert inner['uuid'] == '52d19e87-24ba-4291-a872-69d963b96ce9'
assert inner['orchestrator'] == 'streaming'
assert inner['provider'] == 'providers:anthropic'
assert len(inner['behaviors']) == 3
assert inner['service']['command'] == 'amplifier-foundation-serve'
print('amplifier-dev.yaml: OK')
"
```
Expected: `amplifier-dev.yaml: OK`

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-foundation/agents/amplifier-dev.yaml && git commit -m "feat: rewrite amplifier-dev agent definition to spec format"
```

---

### Task 8: Rewrite `default.yaml` agent definition

**Files:**
- Modify: `services/amplifier-foundation/agents/default.yaml`

This is the full-featured foundation agent that includes ALL behaviors. The behavior URLs must use the canonical raw GitHub URL format (not `refs/heads/main`), and all behavior files must have `.yaml` extensions in the URL.

**Step 1: Rewrite the file**

Replace `services/amplifier-foundation/agents/default.yaml` entirely. This agent includes the full set of foundation behaviors plus external service behaviors:

```yaml
agent:
  ref: foundation
  uuid: 3898a638-71de-427a-8183-b80eba8b26be
  version: 1
  description: Full-featured foundation agent with all capabilities

  orchestrator: streaming
  context_manager: simple
  provider: providers:anthropic

  tools: true
  hooks: true
  agents: true
  context: true

  behaviors:
    # Foundation behaviors (served by this agent's own service)
    - agents: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/agents.yaml
    - amplifier-dev-behavior: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/amplifier-dev.yaml
    - foundation-expert: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/foundation-expert.yaml
    - logging: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/logging.yaml
    - progress-monitor: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/progress-monitor.yaml
    - redaction: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/redaction.yaml
    - sessions: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/sessions.yaml
    - shadow-amplifier: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/shadow-amplifier.yaml
    - status-context: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/status-context.yaml
    - streaming-ui: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/streaming-ui.yaml
    - tasks: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/tasks.yaml
    - todo-reminder: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/todo-reminder.yaml

    # External service behaviors
    - modes: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-modes/behaviors/modes.yaml
    - skills: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-skills/behaviors/skills.yaml
    - skills-tool: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-skills/behaviors/skills-tool.yaml
    - routing: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-routing-matrix/behaviors/routing.yaml
    - recipes: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-recipes/behaviors/recipes.yaml
    - apply-patch: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-filesystem/behaviors/apply-patch.yaml
    - superpowers-methodology: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-superpowers/behaviors/superpowers-methodology.yaml

    # Content-serving behaviors
    - amplifier-expert: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-amplifier/behaviors/amplifier-expert.yaml
    - amplifier-dev-hygiene: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-amplifier/behaviors/amplifier-dev.yaml
    - core-expert: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-core/behaviors/core-expert.yaml
    - design-intelligence: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-design-intelligence/behaviors/design-intelligence.yaml
    - browser-tester: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-browser-tester/behaviors/browser-tester.yaml

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-foundation
    command: amplifier-foundation-serve
```

**Step 2: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
data = yaml.safe_load(open('services/amplifier-foundation/agents/default.yaml'))
inner = data['agent']
assert inner['ref'] == 'foundation'
assert inner['uuid'] == '3898a638-71de-427a-8183-b80eba8b26be'
assert inner['service']['stack'] == 'uv'
assert inner['service']['command'] == 'amplifier-foundation-serve'
# Verify all behavior entries are {alias: url} dicts
for b in inner['behaviors']:
    assert isinstance(b, dict), f'Expected dict, got {type(b)}: {b}'
    assert len(b) == 1, f'Expected single-key dict, got {b}'
print(f'default.yaml: OK ({len(inner[\"behaviors\"])} behaviors)')
"
```
Expected: `default.yaml: OK (24 behaviors)` (or however many are included).

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-foundation/agents/default.yaml && git commit -m "feat: rewrite default (foundation) agent definition to spec format with all behaviors"
```

---

### Task 9: Rewrite `minimal.yaml`, `with-anthropic.yaml`, `with-openai.yaml`

**Files:**
- Modify: `services/amplifier-foundation/agents/minimal.yaml`
- Modify: `services/amplifier-foundation/agents/with-anthropic.yaml`
- Modify: `services/amplifier-foundation/agents/with-openai.yaml`

These are currently in old bundle format (class references, `includes:`). They need full rewrites to IPC format. Each needs a new UUID.

**Step 1: Rewrite `minimal.yaml`**

A stripped-down agent with basic foundation capabilities but no external behaviors:

```yaml
agent:
  ref: minimal
  uuid: <generate-fresh-uuid>
  version: 1
  description: Minimal foundation agent with basic tools and hooks

  orchestrator: streaming
  context_manager: simple
  provider: providers:anthropic

  tools: true
  hooks: true
  context: true

  behaviors:
    - todo-reminder: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/todo-reminder.yaml
    - status-context: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/status-context.yaml
    - sessions: https://raw.githubusercontent.com/payneio/amplifier-ipc/main/services/amplifier-foundation/behaviors/sessions.yaml

  service:
    stack: uv
    source: git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/amplifier-foundation
    command: amplifier-foundation-serve
```

**Step 2: Rewrite `with-anthropic.yaml`**

An agent that explicitly sets the Anthropic provider. Includes a baseline set of behaviors:

```yaml
agent:
  ref: with-anthropic
  uuid: <generate-fresh-uuid>
  version: 1
  description: Foundation agent with Anthropic provider explicitly set

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

**Step 3: Rewrite `with-openai.yaml`**

Same as `with-anthropic` but with OpenAI provider:

```yaml
agent:
  ref: with-openai
  uuid: <generate-fresh-uuid>
  version: 1
  description: Foundation agent with OpenAI provider explicitly set

  orchestrator: streaming
  context_manager: simple
  provider: providers:openai

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

**Step 4: Verify all three**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
for f in [
    'services/amplifier-foundation/agents/minimal.yaml',
    'services/amplifier-foundation/agents/with-anthropic.yaml',
    'services/amplifier-foundation/agents/with-openai.yaml',
]:
    data = yaml.safe_load(open(f))
    inner = data['agent']
    assert inner.get('ref'), f'{f}: missing ref'
    assert inner.get('uuid'), f'{f}: missing uuid'
    assert inner.get('service', {}).get('command'), f'{f}: missing service.command'
    print(f'{f}: OK ({inner[\"ref\"]})')
"
```
Expected: All three print `OK`.

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/amplifier-foundation/agents/minimal.yaml services/amplifier-foundation/agents/with-anthropic.yaml services/amplifier-foundation/agents/with-openai.yaml && git commit -m "feat: rewrite minimal, with-anthropic, with-openai agent definitions to spec format"
```

---

### Task 10: Create `.amplifier/settings.yaml` for local dev overrides

**Files:**
- Create: `.amplifier/settings.yaml`

**Step 1: Create the directory and file**

```bash
mkdir -p /data/labs/amplifier-ipc/.amplifier
```

Create `.amplifier/settings.yaml` with:

```yaml
# Local development overrides for amplifier-ipc services.
# These use `uv run --directory` to run directly from source,
# so code changes are immediately reflected without reinstalling.

amplifier_ipc:
  service_overrides:
    amplifier-dev:
      foundation:
        command: ["uv", "run", "--directory", "./services/amplifier-foundation", "amplifier-foundation-serve"]
        working_dir: ./services/amplifier-foundation
      modes:
        command: ["uv", "run", "--directory", "./services/amplifier-modes", "amplifier-modes-serve"]
        working_dir: ./services/amplifier-modes
      skills:
        command: ["uv", "run", "--directory", "./services/amplifier-skills", "amplifier-skills-serve"]
        working_dir: ./services/amplifier-skills
      routing:
        command: ["uv", "run", "--directory", "./services/amplifier-routing-matrix", "amplifier-routing-matrix-serve"]
        working_dir: ./services/amplifier-routing-matrix
      superpowers-methodology:
        command: ["uv", "run", "--directory", "./services/amplifier-superpowers", "amplifier-superpowers-serve"]
        working_dir: ./services/amplifier-superpowers
      recipes:
        command: ["uv", "run", "--directory", "./services/amplifier-recipes", "amplifier-recipes-serve"]
        working_dir: ./services/amplifier-recipes
      apply-patch:
        command: ["uv", "run", "--directory", "./services/amplifier-filesystem", "amplifier-filesystem-serve"]
        working_dir: ./services/amplifier-filesystem
```

**Step 2: Verify YAML is valid**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
import yaml
data = yaml.safe_load(open('.amplifier/settings.yaml'))
overrides = data['amplifier_ipc']['service_overrides']['amplifier-dev']
print(f'Override keys: {list(overrides.keys())}')
assert 'foundation' in overrides
assert 'modes' in overrides
assert overrides['modes']['command'][0] == 'uv'
print('settings.yaml: OK')
"
```
Expected: Prints override keys and `settings.yaml: OK`.

**Step 3: Add to .gitignore**

This is a local dev override file — typically it should NOT be committed because each developer's paths may differ. Add `.amplifier/` to `.gitignore`:

```bash
cd /data/labs/amplifier-ipc && grep -q '.amplifier/' .gitignore 2>/dev/null && echo "already ignored" || echo ".amplifier/" >> .gitignore
```

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add .amplifier/settings.yaml .gitignore && git commit -m "feat: add local dev settings.yaml with service overrides for uv run --directory"
```

---

### Task 11: Write the definition-validation test suite

**Files:**
- Create: `tests/host/test_definition_files.py`

This test suite parametrically validates every YAML definition file in the `services/` tree against the spec.

**Step 1: Write the test file**

Create `tests/host/test_definition_files.py` with:

```python
"""Validate all YAML definition files against the spec.

Parametrized tests that scan the services/ tree, find every agent and behavior
definition, and verify each conforms to the spec:
  - Has 'agent:' or 'behavior:' as top-level key
  - Has 'ref' and 'uuid' inside the wrapper
  - UUID is valid UUID v4 format
  - If 'service:' is present, it has stack, source, and command
  - 'behaviors:' entries are {alias: url} dicts (if present)
  - Parseable by the appropriate parser function
"""

from __future__ import annotations

import uuid as uuid_mod
from pathlib import Path

import pytest
import yaml

from amplifier_ipc.cli.commands.discover import scan_location
from amplifier_ipc.host.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    parse_agent_definition,
    parse_behavior_definition,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
SERVICES_DIR = PROJECT_ROOT / "services"


def _collect_definitions() -> list[dict]:
    """Scan services/ and return all definition file metadata."""
    results = scan_location(str(SERVICES_DIR))
    # Augment each result with its parsed YAML for deeper inspection
    for r in results:
        raw = yaml.safe_load(r["raw_content"])
        r["_parsed"] = raw
    return results


DEFINITIONS = _collect_definitions()
AGENT_DEFS = [d for d in DEFINITIONS if d["type"] == "agent"]
BEHAVIOR_DEFS = [d for d in DEFINITIONS if d["type"] == "behavior"]


# ---------------------------------------------------------------------------
# All definitions: structural validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "defn",
    DEFINITIONS,
    ids=[f"{d['type']}:{d['ref']}" for d in DEFINITIONS],
)
def test_definition_has_ref(defn: dict) -> None:
    """Every definition must have a non-empty 'ref' field."""
    assert defn["ref"], f"Missing ref in {defn['path']}"


@pytest.mark.parametrize(
    "defn",
    DEFINITIONS,
    ids=[f"{d['type']}:{d['ref']}" for d in DEFINITIONS],
)
def test_definition_has_valid_uuid(defn: dict) -> None:
    """Every definition must have a valid UUID."""
    raw = defn["_parsed"]
    inner = raw.get(defn["type"], {})
    uuid_str = inner.get("uuid", "")
    assert uuid_str, f"Missing uuid in {defn['path']}"
    # Must be parseable as a UUID
    parsed = uuid_mod.UUID(str(uuid_str))
    assert parsed.version == 4, (
        f"Expected UUID v4, got version {parsed.version} in {defn['path']}"
    )


@pytest.mark.parametrize(
    "defn",
    DEFINITIONS,
    ids=[f"{d['type']}:{d['ref']}" for d in DEFINITIONS],
)
def test_definition_has_no_old_format_fields(defn: dict) -> None:
    """No definition should use old-format fields (type, local_ref, services, installer, name)."""
    raw = defn["_parsed"]
    inner = raw.get(defn["type"], {})
    assert "type" not in raw, f"Found old 'type:' key in {defn['path']}"
    assert "local_ref" not in inner, f"Found old 'local_ref:' in {defn['path']}"
    assert "services" not in inner, f"Found old plural 'services:' in {defn['path']}"
    assert "installer" not in inner, f"Found old 'installer:' in {defn['path']}"
    if isinstance(inner.get("service"), dict):
        assert "name" not in inner["service"], (
            f"Found old 'name:' in service block of {defn['path']}"
        )
        assert "installer" not in inner["service"], (
            f"Found old 'installer:' in service block of {defn['path']}"
        )


@pytest.mark.parametrize(
    "defn",
    DEFINITIONS,
    ids=[f"{d['type']}:{d['ref']}" for d in DEFINITIONS],
)
def test_definition_service_block_is_valid(defn: dict) -> None:
    """If service: is present, it must have stack, source, and command."""
    raw = defn["_parsed"]
    inner = raw.get(defn["type"], {})
    service = inner.get("service")
    if service is None:
        return  # No service block is valid (content-only)
    assert isinstance(service, dict), f"service: must be a dict in {defn['path']}"
    assert service.get("stack"), f"service.stack missing in {defn['path']}"
    assert service.get("source"), f"service.source missing in {defn['path']}"
    assert service.get("command"), f"service.command missing in {defn['path']}"


@pytest.mark.parametrize(
    "defn",
    DEFINITIONS,
    ids=[f"{d['type']}:{d['ref']}" for d in DEFINITIONS],
)
def test_definition_behaviors_format(defn: dict) -> None:
    """If behaviors: is present, entries must be {alias: url} dicts or empty list."""
    raw = defn["_parsed"]
    inner = raw.get(defn["type"], {})
    behaviors = inner.get("behaviors")
    if behaviors is None or behaviors == []:
        return
    assert isinstance(behaviors, list), (
        f"behaviors: must be a list in {defn['path']}"
    )
    for entry in behaviors:
        assert isinstance(entry, dict), (
            f"Each behavior entry must be a {{alias: url}} dict, "
            f"got {type(entry).__name__}: {entry!r} in {defn['path']}"
        )
        assert len(entry) == 1, (
            f"Each behavior dict must have exactly 1 key, "
            f"got {len(entry)}: {entry!r} in {defn['path']}"
        )


# ---------------------------------------------------------------------------
# Agent definitions: parseable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "defn",
    AGENT_DEFS,
    ids=[d["ref"] for d in AGENT_DEFS],
)
def test_agent_definition_parseable(defn: dict) -> None:
    """Every agent definition must be parseable by parse_agent_definition()."""
    result = parse_agent_definition(defn["raw_content"])
    assert isinstance(result, AgentDefinition)
    assert result.ref == defn["ref"]


@pytest.mark.parametrize(
    "defn",
    AGENT_DEFS,
    ids=[d["ref"] for d in AGENT_DEFS],
)
def test_agent_has_orchestrator(defn: dict) -> None:
    """Agent definitions should have an orchestrator."""
    result = parse_agent_definition(defn["raw_content"])
    assert result.orchestrator, f"Agent {defn['ref']} has no orchestrator"


# ---------------------------------------------------------------------------
# Behavior definitions: parseable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "defn",
    BEHAVIOR_DEFS,
    ids=[d["ref"] for d in BEHAVIOR_DEFS],
)
def test_behavior_definition_parseable(defn: dict) -> None:
    """Every behavior definition must be parseable by parse_behavior_definition()."""
    result = parse_behavior_definition(defn["raw_content"])
    assert isinstance(result, BehaviorDefinition)
    assert result.ref == defn["ref"]


# ---------------------------------------------------------------------------
# Behavior definitions: config block validation
# ---------------------------------------------------------------------------

BEHAVIORS_WITH_CONFIG = {
    "agents", "tasks", "todo-reminder", "streaming-ui", "status-context",
    "sessions", "redaction", "progress-monitor", "logging",
    "routing", "skills", "skills-tool", "apply-patch", "recipes",
    "superpowers-methodology",
}


@pytest.mark.parametrize(
    "defn",
    [d for d in BEHAVIOR_DEFS if d["ref"] in BEHAVIORS_WITH_CONFIG],
    ids=[d["ref"] for d in BEHAVIOR_DEFS if d["ref"] in BEHAVIORS_WITH_CONFIG],
)
def test_behavior_with_config_has_config_block(defn: dict) -> None:
    """Behaviors that had config in old format must have config: block in new format."""
    raw = defn["_parsed"]
    inner = raw.get("behavior", {})
    config = inner.get("config")
    assert config is not None and isinstance(config, dict), (
        f"Behavior '{defn['ref']}' should have a config: block but doesn't. "
        f"Path: {defn['path']}"
    )
    assert len(config) > 0, (
        f"Behavior '{defn['ref']}' has an empty config: block. "
        f"Path: {defn['path']}"
    )


@pytest.mark.parametrize(
    "defn",
    [d for d in BEHAVIOR_DEFS if d["ref"] in BEHAVIORS_WITH_CONFIG],
    ids=[d["ref"] for d in BEHAVIOR_DEFS if d["ref"] in BEHAVIORS_WITH_CONFIG],
)
def test_config_keys_are_component_names(defn: dict) -> None:
    """Config block keys must be bare component names (no ref: prefix in behaviors)."""
    raw = defn["_parsed"]
    inner = raw.get("behavior", {})
    config = inner.get("config", {})
    for key in config:
        assert ":" not in key, (
            f"Behavior config key '{key}' should be a bare component name "
            f"(no ref: prefix). Prefixed keys are only valid in agent config. "
            f"Path: {defn['path']}"
        )


# ---------------------------------------------------------------------------
# Discovery: scan_location finds all expected definitions
# ---------------------------------------------------------------------------


def test_scan_finds_all_agent_definitions() -> None:
    """scan_location(services/) must find all agent definitions."""
    agent_refs = {d["ref"] for d in AGENT_DEFS}
    expected = {"amplifier-dev", "foundation", "minimal", "with-anthropic", "with-openai"}
    missing = expected - agent_refs
    assert not missing, f"Missing agent definitions: {missing}. Found: {agent_refs}"


def test_scan_finds_expected_behavior_definitions() -> None:
    """scan_location(services/) must find key behavior definitions."""
    behavior_refs = {d["ref"] for d in BEHAVIOR_DEFS}
    expected = {"modes", "skills", "routing", "recipes", "apply-patch"}
    missing = expected - behavior_refs
    assert not missing, (
        f"Missing behavior definitions: {missing}. Found: {behavior_refs}"
    )
```

**Step 2: Run the test suite**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_definition_files.py -v
```
Expected: All PASS. If any fail, the corresponding definition file needs fixing (go back to the relevant task and correct it).

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add tests/host/test_definition_files.py && git commit -m "test: add comprehensive definition-validation test suite for all YAML files"
```

---

### Task 12: Update `test_lifecycle.py` and run full test suite

**Files:**
- Modify: `tests/cli/test_lifecycle.py`

The lifecycle tests reference old format (`local_ref`, `services`, specific counts). Update them for the new format.

**Step 1: Rewrite `test_lifecycle.py`**

Replace the entire file content with:

```python
"""Integration tests for the full discover -> register -> install lifecycle.

Tests:
1. test_discover_finds_definitions -- discover services/ finds agents and behaviors
2. test_discover_register_creates_alias_files -- after --register, alias files populated
3. test_registered_definitions_are_valid -- stored defs have correct nested structure
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from amplifier_ipc.cli.main import cli

SERVICES_DIR = Path(__file__).parent.parent.parent / "services"


def test_discover_finds_definitions() -> None:
    """discover services/ finds agent and behavior definitions."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", str(SERVICES_DIR)])

    assert result.exit_code == 0, result.output
    assert "Found" in result.output
    assert "[agent]" in result.output
    assert "[behavior]" in result.output


def test_discover_register_creates_alias_files(tmp_path: Path) -> None:
    """After discover --register, agents.yaml and behaviors.yaml have entries."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", str(SERVICES_DIR), "--register", "--home", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output

    agents = yaml.safe_load((tmp_path / "agents.yaml").read_text()) or {}
    assert len(agents) > 0, "agents.yaml should have at least one entry"

    behaviors = yaml.safe_load((tmp_path / "behaviors.yaml").read_text()) or {}
    assert len(behaviors) > 0, "behaviors.yaml should have at least one entry"


def test_registered_definitions_are_valid(tmp_path: Path) -> None:
    """Definitions stored in definitions/ use the new nested format."""
    runner = CliRunner()
    runner.invoke(
        cli,
        ["discover", str(SERVICES_DIR), "--register", "--home", str(tmp_path)],
    )

    defs_dir = tmp_path / "definitions"
    for def_file in sorted(defs_dir.glob("*.yaml")):
        stored = yaml.safe_load(def_file.read_text()) or {}
        # Must have agent: or behavior: as top-level key (ignore _meta)
        top_keys = {k for k in stored if not k.startswith("_")}
        assert top_keys & {"agent", "behavior"}, (
            f"{def_file.name}: no agent: or behavior: key found. Keys: {top_keys}"
        )
```

**Step 2: Run all tests**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/ -v --ignore=tests/e2e/ --ignore=tests/host/test_e2e_mock.py
```
Expected: All PASS.

**Step 3: Run linting**

```bash
cd /data/labs/amplifier-ipc && uv run ruff check tests/host/test_definition_files.py tests/cli/test_lifecycle.py
```
Expected: No errors.

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add tests/cli/test_lifecycle.py && git commit -m "test: update lifecycle tests for new nested definition format"
```

---

### Task 13: Final verification — full test suite

**Step 1: Run the complete test suite**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/ -v --ignore=tests/e2e/ --ignore=tests/host/test_e2e_mock.py
```
Expected: All PASS.

**Step 2: Verify definition file count**

```bash
cd /data/labs/amplifier-ipc && uv run python -c "
from amplifier_ipc.cli.commands.discover import scan_location
results = scan_location('services')
agents = [r for r in results if r['type'] == 'agent']
behaviors = [r for r in results if r['type'] == 'behavior']
print(f'Agents: {len(agents)} -- {[r[\"ref\"] for r in agents]}')
print(f'Behaviors: {len(behaviors)} -- {[r[\"ref\"] for r in behaviors]}')
print(f'Total: {len(results)} definitions')
# No *-ipc.yaml files should exist
import glob
ipc_files = glob.glob('services/*/behaviors/*-ipc.yaml')
assert not ipc_files, f'Old -ipc.yaml files still exist: {ipc_files}'
print('No -ipc.yaml files found. Clean!')
"
```
Expected: 5 agents, ~24 behaviors, no `-ipc.yaml` files.

**Step 3: Final commit**

```bash
cd /data/labs/amplifier-ipc && git add -A && git commit -m "chore: phase 2 definition alignment complete"
```

---

## Summary of Phase 2 Changes

| Category | Files | Action |
|----------|-------|--------|
| Delete | 5 `*-ipc.yaml` files | Removed obsolete flat-format files |
| Rewrite (external service) | `modes.yaml`, `skills.yaml`, `skills-tool.yaml`, `routing.yaml`, `superpowers-methodology.yaml`, `recipes.yaml`, `apply-patch.yaml` | New format with `service:` block. `skills.yaml`, `skills-tool.yaml`, `routing.yaml`, `superpowers-methodology.yaml`, `recipes.yaml`, `apply-patch.yaml` include `config:` blocks. |
| Rewrite (foundation) | `agents.yaml`, `amplifier-dev.yaml`, `foundation-expert.yaml`, `logging.yaml`, `progress-monitor.yaml`, `redaction.yaml`, `sessions.yaml`, `shadow-amplifier.yaml`, `status-context.yaml`, `streaming-ui.yaml`, `tasks.yaml`, `todo-reminder.yaml` | New format, no `service:` block. `agents.yaml`, `logging.yaml`, `progress-monitor.yaml`, `redaction.yaml`, `sessions.yaml`, `status-context.yaml`, `streaming-ui.yaml`, `tasks.yaml`, `todo-reminder.yaml` include `config:` blocks. |
| Rewrite (content-serving) | `amplifier-expert.yaml`, `amplifier-dev.yaml` (amplifier), `core-expert.yaml`, `design-intelligence.yaml`, `browser-tester.yaml` | New format with `service:` block |
| Rewrite (agents) | `amplifier-dev.yaml`, `default.yaml`, `minimal.yaml`, `with-anthropic.yaml`, `with-openai.yaml` | Full spec format with behaviors URLs |
| Create | `.amplifier/settings.yaml` | Local dev overrides |
| Create | `tests/host/test_definition_files.py` | Comprehensive validation suite including config block validation for 15 behaviors |
| Modify | `tests/cli/test_lifecycle.py` | Updated for new format |
