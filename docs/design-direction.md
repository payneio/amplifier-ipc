## Overview

- Each agent or behavior with a "service" section gets installed and registered using it's UUID.

## Usage

Installation.

```bash
uv tool install git+https://github.com/payneio/amplifier-ipc`
```

Add agents and behaviors.

```bash
# Find all agents and behaviors at the location provided (git or fsspec).
amplifier-ipc discover git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/foundation --register --install

# The above will run this for every agent and behavior discovered.
amplifier-ipc register <fsspec> --install
```

Every agent and behavior must have a GUID, a local_ref (for reference in the description tree), and may have service install instructions.

```bash
# This is just pseudo-code for the types of things we need and where to get them. Python funcs will handle all this.
REF='yq .local_ref -f $URI'
GUID='yq .guid -f $URI'
ID="<agent|behavior>_$REF_$GUID"
```

The `register` command will cache the definition locally to `${AMPLIFIER_HOME}/definitions/${ID}.yaml`
and register the definition in `agents.yaml` and `behaviors.yaml` with aliases ($REF by default) pointing to the $ID.

You can optionally run `amplifier-ipc install <agent>`, but it will also run the first time you try to use it.

```bash
amp-ipc run --agent <agent> --add-behavior <behavior> --session <session id> “<message>” --project <project name> --working-dir <fsspec>`
```

- Look up agent ID from AMPLIFIER_HOME/agents.yaml
- Walk all agents and behaviors.
  - If service installer is uv:
    - Make sure venv exists. Make sure all sources have been installed in it.
- Run the service execute tool from that environment. It will construct a list of the names of all the behavior service tools (their script names) and will call them as necessary to orchestrate a response.

```bash
ENVIRONMENT=AMPLIFIER_HOME/environments/$ID
uv venv --create $ENVIRONMENT
$PYTHON=$ENVIRONMENT/bin/python
uv pip install --python $PYTHON <source>
```

Creates a new process to run the service/tool: `uv run --venv $ENVIRONMENT <entrypoint>` (entrypoint defaults to `run` if not declared)

- Host tool merges agent+behavior definitions, creates in-memory map of names->service:tool for the orchestrator and other tools to reference, and orchestrates tool requests, streaming responses over stdout, logs over stderr while managing session data.

## Advanced Usage

OCTHP+Content can all be overridden locally in icp-overrides.yaml.

You can create custom agents and behaviors locally that 

## Agent and Behavior Definitions

### A behavior definition

```yaml
# amplifier-dev behavior
behavior:
  local_ref: amplifier-dev-behavior
  uuid: a6a2e2b5-8dd0-40ce-b2c7-327e4e62b645
  version: 2
  description: Amplifier ecosystem development behavior - multi-repo workflows, testing patterns, and ecosystem expertise.

  tools: True
   - amplifier-dev-behavior:bundle_shadow

  context: True
  agents:
    include:
    - foundation:ecosystem-expert

  behaviors:
    - design-intelligence: https://raw.github.com/microsoft/amplifier-design-intelligence/main/behavior.yaml

  service:
    installer: uv
    source: git+https://github.com/microsoft/amplifier-ipc@main#subdirectory=/services/amplifier-dev

```

### An agent definition

```yaml
# amplifier-dev agent
agent:
  local_ref: amplifier-dev
  uuid: e6a49802-fd80-4026-b9b8-2a790a0ccb5e
  version: 2
  description: Amplifier ecosystem development agent - multi-repo workflows, testing patterns, and ecosystem expertise.
  base: https://raw.github.com/microsoft/amplifier-ipc/main/agents/foundation.md

  behaviors:
    - amplifier-dev-behavior: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/amplifier-dev

```

### Another agent definition

```yaml

# Foundation agent
agent:
  local_ref: foundation
  uuid: 3898a638-71de-427a-8183-b80eba8b26be

  orchestrator: foundation:streaming
  context_manager: foundation:simple
  tools: True
  hooks: True
  agents: True
  context: True

  behaviors:
    - agents: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/agents.yaml
    - amplifier-dev: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/amplifier-dev.yaml
    - foundation-expert: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/foundation-expert.yaml
    - logging: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/logging
    - progress-monitor: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/progress-monitor
    - redaction: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/redaction
    - sessions: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/sessions
    - shadow-amplifier: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/shadow-amplifier
    - status-context: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/status-context
    - streaming-ui: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/streaming-ui
    - tasks: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/tasks
    - todo-reminder: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/todo-reminder
    - skills: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/skills.yaml
    - amplifier-expert: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/amplifier-expert.yaml
    - core-expert: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/core-expert.yaml
    - recipes: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/recipes.yaml
    - design-intelligence: https://raw.github.com/microsoft/amplifier-design-intelligence/main/behavior.yaml
    - skills-tool: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/skills-tool.yaml
    - browser-tester: https://raw.github.com/microsoft/amplifier-bundle-browser-tester/main/behavior.yaml
    - superpowers-methodology: https://raw.github.com/microsoft/amplifier-bundle-superpowers/main/behavior.yaml
    - apply-patch: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/apply-patch.yaml
    - routing: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/routing.yaml
    - modes: https://raw.github.com/microsoft/amplifier-module-tool-modes/main/behavior.yaml

  service:
    installer: uv
    source: git+https://github.com/microsoft/amplifier-ipc@main#subdirectory=/services/foundation

