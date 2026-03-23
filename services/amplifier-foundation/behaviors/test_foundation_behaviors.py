"""
TDD validation tests for foundation behavior files.
These tests verify the NEW spec format (ref, uuid, no service block).
Run BEFORE rewriting to see RED, then AFTER to confirm GREEN.
"""
import yaml
import re
from pathlib import Path

BEHAVIORS_DIR = Path(__file__).parent
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

FILES = [
    "agents.yaml",
    "amplifier-dev.yaml",
    "foundation-expert.yaml",
    "logging.yaml",
    "progress-monitor.yaml",
    "redaction.yaml",
]


def load(filename):
    path = BEHAVIORS_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def test_all_have_behavior_top_level_key():
    for filename in FILES:
        doc = load(filename)
        assert "behavior" in doc, f"{filename}: missing top-level 'behavior' key"
        print(f"  {filename}: has 'behavior' key ✓")


def test_all_have_ref_not_name():
    for filename in FILES:
        doc = load(filename)
        inner = doc["behavior"]
        assert "ref" in inner, f"{filename}: missing 'ref' field"
        assert "name" not in inner, f"{filename}: should NOT have 'name' field (use 'ref')"
        print(f"  {filename}: has 'ref'={inner['ref']} ✓")


def test_all_have_uuid():
    for filename in FILES:
        doc = load(filename)
        inner = doc["behavior"]
        assert "uuid" in inner, f"{filename}: missing 'uuid' field"
        uuid_val = str(inner["uuid"])
        assert UUID_RE.match(uuid_val), f"{filename}: uuid '{uuid_val}' is not valid UUID format"
        print(f"  {filename}: has valid uuid ✓")


def test_no_service_block():
    for filename in FILES:
        doc = load(filename)
        inner = doc["behavior"]
        assert "service" not in inner, f"{filename}: MUST NOT have 'service' block (foundation behaviors have no service)"
        print(f"  {filename}: no 'service' block ✓")


def test_all_have_version():
    for filename in FILES:
        doc = load(filename)
        inner = doc["behavior"]
        assert "version" in inner, f"{filename}: missing 'version' field"
        assert inner["version"] == 1, f"{filename}: version should be 1, got {inner['version']}"
        print(f"  {filename}: version=1 ✓")


def test_all_have_behaviors_list():
    for filename in FILES:
        doc = load(filename)
        inner = doc["behavior"]
        assert "behaviors" in inner, f"{filename}: missing 'behaviors' list"
        assert inner["behaviors"] == [], f"{filename}: 'behaviors' should be empty list []"
        print(f"  {filename}: behaviors=[] ✓")


def test_agents_yaml_specific():
    doc = load("agents.yaml")
    inner = doc["behavior"]
    assert inner["ref"] == "agents", f"agents.yaml: ref should be 'agents', got '{inner['ref']}'"
    assert inner.get("tools") is True, "agents.yaml: tools should be True"
    assert inner.get("context") is True, "agents.yaml: context should be True"
    config = inner.get("config", {})
    assert "delegate-tool" in config, "agents.yaml: config missing 'delegate-tool'"
    dt = config["delegate-tool"]
    assert "features" in dt, "agents.yaml: delegate-tool missing 'features'"
    assert dt["features"].get("parallel") is True, "agents.yaml: delegate-tool.features.parallel should be True"
    assert dt["features"].get("context_sharing") is True, "agents.yaml: delegate-tool.features.context_sharing should be True"
    assert "settings" in dt, "agents.yaml: delegate-tool missing 'settings'"
    assert dt["settings"].get("max_concurrent") == 4, "agents.yaml: max_concurrent should be 4"
    assert "skills-tool" in config, "agents.yaml: config missing 'skills-tool'"
    assert config["skills-tool"].get("skills") == [], "agents.yaml: skills-tool.skills should be []"
    print("  agents.yaml: all specific fields OK ✓")


def test_amplifier_dev_yaml_specific():
    doc = load("amplifier-dev.yaml")
    inner = doc["behavior"]
    assert inner["ref"] == "amplifier-dev-behavior", \
        f"amplifier-dev.yaml: ref should be 'amplifier-dev-behavior', got '{inner['ref']}'"
    assert inner.get("context") is True, "amplifier-dev.yaml: context should be True"
    print("  amplifier-dev.yaml: all specific fields OK ✓")


def test_foundation_expert_yaml_specific():
    doc = load("foundation-expert.yaml")
    inner = doc["behavior"]
    assert inner["ref"] == "foundation-expert", \
        f"foundation-expert.yaml: ref should be 'foundation-expert', got '{inner['ref']}'"
    assert inner.get("context") is True, "foundation-expert.yaml: context should be True"
    print("  foundation-expert.yaml: all specific fields OK ✓")


def test_logging_yaml_specific():
    doc = load("logging.yaml")
    inner = doc["behavior"]
    assert inner["ref"] == "logging", f"logging.yaml: ref should be 'logging', got '{inner['ref']}'"
    assert inner.get("hooks") is True, "logging.yaml: hooks should be True"
    config = inner.get("config", {})
    assert "logging-hook" in config, "logging.yaml: config missing 'logging-hook'"
    lh = config["logging-hook"]
    assert lh.get("mode") == "jsonl", f"logging.yaml: logging-hook.mode should be 'jsonl', got '{lh.get('mode')}'"
    assert "template" in lh, "logging.yaml: logging-hook missing 'template'"
    assert "{session_id}" in lh["template"], "logging.yaml: template should contain {session_id}"
    print("  logging.yaml: all specific fields OK ✓")


def test_progress_monitor_yaml_specific():
    doc = load("progress-monitor.yaml")
    inner = doc["behavior"]
    assert inner["ref"] == "progress-monitor", \
        f"progress-monitor.yaml: ref should be 'progress-monitor', got '{inner['ref']}'"
    assert inner.get("hooks") is True, "progress-monitor.yaml: hooks should be True"
    config = inner.get("config", {})
    assert "progress-monitor-hook" in config, "progress-monitor.yaml: config missing 'progress-monitor-hook'"
    pmh = config["progress-monitor-hook"]
    assert pmh.get("read_threshold") == 30, \
        f"progress-monitor.yaml: read_threshold should be 30, got '{pmh.get('read_threshold')}'"
    assert pmh.get("max_turns") == 10, \
        f"progress-monitor.yaml: max_turns should be 10, got '{pmh.get('max_turns')}'"
    print("  progress-monitor.yaml: all specific fields OK ✓")


def test_redaction_yaml_specific():
    doc = load("redaction.yaml")
    inner = doc["behavior"]
    assert inner["ref"] == "redaction", \
        f"redaction.yaml: ref should be 'redaction', got '{inner['ref']}'"
    assert inner.get("hooks") is True, "redaction.yaml: hooks should be True"
    config = inner.get("config", {})
    assert "redaction-hook" in config, "redaction.yaml: config missing 'redaction-hook'"
    rh = config["redaction-hook"]
    assert "allowlist" in rh, "redaction.yaml: redaction-hook missing 'allowlist'"
    al = rh["allowlist"]
    assert "session_id" in al, "redaction.yaml: allowlist should contain 'session_id'"
    assert "turn_id" in al, "redaction.yaml: allowlist should contain 'turn_id'"
    print("  redaction.yaml: all specific fields OK ✓")


if __name__ == "__main__":
    tests = [
        test_all_have_behavior_top_level_key,
        test_all_have_ref_not_name,
        test_all_have_uuid,
        test_no_service_block,
        test_all_have_version,
        test_all_have_behaviors_list,
        test_agents_yaml_specific,
        test_amplifier_dev_yaml_specific,
        test_foundation_expert_yaml_specific,
        test_logging_yaml_specific,
        test_progress_monitor_yaml_specific,
        test_redaction_yaml_specific,
    ]
    passed = 0
    failed = 0
    for test in tests:
        print(f"\n{test.__name__}:")
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        exit(1)
