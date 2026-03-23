"""
Validation tests for rewritten external service behavior YAML files.
Each file must have: behavior.ref, behavior.uuid, behavior.service.command
"""

import yaml
import sys

FILES = {
    "modes": "services/amplifier-modes/behaviors/modes.yaml",
    "skills": "services/amplifier-skills/behaviors/skills.yaml",
    "skills-tool": "services/amplifier-skills/behaviors/skills-tool.yaml",
    "routing": "services/amplifier-routing-matrix/behaviors/routing.yaml",
}

EXPECTED = {
    "modes": {
        "ref": "modes",
        "uuid": "6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139",
        "service_command": "amplifier-modes-serve",
        "service_stack": "uv",
        "tools": True,
        "hooks": True,
        "context": True,
    },
    "skills": {
        "ref": "skills",
        "uuid": "6108ceb2-3fbb-4ac3-aa5d-2e1d2dcaabce",
        "service_command": "amplifier-skills-serve",
        "service_stack": "uv",
        "tools": True,
        "context": True,
        "config_skills_tool_skills": [],
        "config_skills_tool_visibility": "full",
    },
    "skills-tool": {
        "ref": "skills-tool",
        # uuid intentionally not pinned — generated fresh during rewrite, any non-empty value is valid
        "service_command": "amplifier-skills-serve",
        "service_stack": "uv",
        "tools": True,
        "context": True,
        "config_skills_tool_visibility": "minimal",
    },
    "routing": {
        "ref": "routing",
        "uuid": "754ff88c-34ea-4e5b-8da6-d7bbbc80682e",
        "service_command": "amplifier-routing-matrix-serve",
        "service_stack": "uv",
        "hooks": True,
        "context": True,
        "config_routing_hook_default_matrix": "balanced",
    },
}


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def check_file(name, path, expected):
    errors = []
    try:
        data = load_yaml(path)
    except Exception as e:
        return [f"Failed to load YAML: {e}"]

    # Check top-level key
    if "behavior" not in data:
        errors.append("Missing top-level 'behavior' key")

    b = data.get("behavior", {})

    # Check ref
    if b.get("ref") != expected.get("ref"):
        errors.append(
            f"ref mismatch: expected '{expected.get('ref')}', got '{b.get('ref')}'"
        )

    # Check uuid (if expected specifies one)
    if "uuid" in expected:
        if b.get("uuid") != expected["uuid"]:
            errors.append(
                f"uuid mismatch: expected '{expected['uuid']}', got '{b.get('uuid')}'"
            )
    else:
        # Just check uuid exists and is non-empty
        if not b.get("uuid"):
            errors.append("uuid is missing or empty")

    # Check service block
    svc = b.get("service", {})
    if not svc:
        errors.append("Missing 'service' block")
    else:
        if svc.get("command") != expected["service_command"]:
            errors.append(
                f"service.command mismatch: expected '{expected['service_command']}', got '{svc.get('command')}'"
            )
        if svc.get("stack") != expected["service_stack"]:
            errors.append(
                f"service.stack mismatch: expected '{expected['service_stack']}', got '{svc.get('stack')}'"
            )
        if not svc.get("source"):
            errors.append("service.source is missing or empty")

    # Check boolean flags
    for flag in ["tools", "hooks", "context"]:
        if flag in expected:
            if b.get(flag) != expected[flag]:
                errors.append(
                    f"'{flag}' flag mismatch: expected {expected[flag]}, got {b.get(flag)}"
                )

    # Check behaviors is a list
    if not isinstance(b.get("behaviors"), list):
        errors.append(f"'behaviors' should be a list, got {type(b.get('behaviors'))}")

    # Check config for skills
    if "config_skills_tool_skills" in expected:
        config = b.get("config", {})
        st = config.get("skills-tool", {})
        if st.get("skills") != expected["config_skills_tool_skills"]:
            errors.append(
                f"config.skills-tool.skills mismatch: expected {expected['config_skills_tool_skills']}, got {st.get('skills')}"
            )

    if "config_skills_tool_visibility" in expected:
        config = b.get("config", {})
        st = config.get("skills-tool", {})
        if st.get("visibility") != expected["config_skills_tool_visibility"]:
            errors.append(
                f"config.skills-tool.visibility mismatch: expected '{expected['config_skills_tool_visibility']}', got '{st.get('visibility')}'"
            )

    # Check config for routing
    if "config_routing_hook_default_matrix" in expected:
        config = b.get("config", {})
        rh = config.get("routing-hook", {})
        if rh.get("default_matrix") != expected["config_routing_hook_default_matrix"]:
            errors.append(
                f"config.routing-hook.default_matrix mismatch: expected '{expected['config_routing_hook_default_matrix']}', got '{rh.get('default_matrix')}'"
            )

    return errors


def main():
    all_passed = True
    for name, path in FILES.items():
        expected = EXPECTED[name]
        errors = check_file(name, path, expected)
        if errors:
            print(f"FAIL: {name} ({path})")
            for e in errors:
                print(f"  - {e}")
            all_passed = False
        else:
            print(f"OK: {name}")

    if not all_passed:
        sys.exit(1)
    else:
        print("\nAll 4 files: OK")


if __name__ == "__main__":
    main()
