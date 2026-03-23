"""
Validation tests for rewritten external service behavior YAML files (task-3).
Covers: superpowers-methodology.yaml, recipes.yaml, apply-patch.yaml
Each file must have: behavior.ref, behavior.uuid, behavior.service.command
"""

import sys
import yaml


FILES = {
    "superpowers-methodology": "services/amplifier-superpowers/behaviors/superpowers-methodology.yaml",
    "recipes": "services/amplifier-recipes/behaviors/recipes.yaml",
    "apply-patch": "services/amplifier-filesystem/behaviors/apply-patch.yaml",
}

EXPECTED = {
    "superpowers-methodology": {
        "ref": "superpowers-methodology",
        "service_command": "amplifier-superpowers-serve",
        "service_stack": "uv",
        "tools": True,
        "hooks": True,
        "context": True,
        "config_mode_tool_gate_policy": "warn",
        "config_mode_hooks_search_paths": [],
        "config_skills_tool_skills": [],
    },
    "recipes": {
        "ref": "recipes",
        "service_command": "amplifier-recipes-serve",
        "service_stack": "uv",
        "tools": True,
        "context": True,
        "config_recipes_tool_session_dir": "~/.amplifier/recipe-sessions",
        "config_recipes_tool_cleanup": True,
    },
    "apply-patch": {
        "ref": "apply-patch",
        "service_command": "amplifier-filesystem-serve",
        "service_stack": "uv",
        "tools": True,
        "context": True,
        "config_apply_patch_tool_engine": "native",
        "config_apply_patch_tool_allowed_paths": [],
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

    # Check uuid exists and is non-empty
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

    config = b.get("config", {})

    # superpowers-methodology specific checks
    if "config_mode_tool_gate_policy" in expected:
        mt = config.get("mode-tool", {})
        if mt.get("gate_policy") != expected["config_mode_tool_gate_policy"]:
            errors.append(
                f"config.mode-tool.gate_policy mismatch: expected '{expected['config_mode_tool_gate_policy']}', got '{mt.get('gate_policy')}'"
            )

    if "config_mode_hooks_search_paths" in expected:
        mh = config.get("mode-hooks", {})
        if mh.get("search_paths") != expected["config_mode_hooks_search_paths"]:
            errors.append(
                f"config.mode-hooks.search_paths mismatch: expected {expected['config_mode_hooks_search_paths']}, got {mh.get('search_paths')}"
            )

    if "config_skills_tool_skills" in expected:
        st = config.get("skills-tool", {})
        if st.get("skills") != expected["config_skills_tool_skills"]:
            errors.append(
                f"config.skills-tool.skills mismatch: expected {expected['config_skills_tool_skills']}, got {st.get('skills')}"
            )

    # recipes specific checks
    if "config_recipes_tool_session_dir" in expected:
        rt = config.get("recipes-tool", {})
        if rt.get("session_dir") != expected["config_recipes_tool_session_dir"]:
            errors.append(
                f"config.recipes-tool.session_dir mismatch: expected '{expected['config_recipes_tool_session_dir']}', got '{rt.get('session_dir')}'"
            )

    if "config_recipes_tool_cleanup" in expected:
        rt = config.get("recipes-tool", {})
        if rt.get("cleanup") != expected["config_recipes_tool_cleanup"]:
            errors.append(
                f"config.recipes-tool.cleanup mismatch: expected {expected['config_recipes_tool_cleanup']}, got {rt.get('cleanup')}"
            )

    # apply-patch specific checks
    if "config_apply_patch_tool_engine" in expected:
        ap = config.get("apply-patch-tool", {})
        if ap.get("engine") != expected["config_apply_patch_tool_engine"]:
            errors.append(
                f"config.apply-patch-tool.engine mismatch: expected '{expected['config_apply_patch_tool_engine']}', got '{ap.get('engine')}'"
            )

    if "config_apply_patch_tool_allowed_paths" in expected:
        ap = config.get("apply-patch-tool", {})
        if ap.get("allowed_paths") != expected["config_apply_patch_tool_allowed_paths"]:
            errors.append(
                f"config.apply-patch-tool.allowed_paths mismatch: expected {expected['config_apply_patch_tool_allowed_paths']}, got {ap.get('allowed_paths')}"
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
        print("\nAll 3 files: OK")


if __name__ == "__main__":
    main()
