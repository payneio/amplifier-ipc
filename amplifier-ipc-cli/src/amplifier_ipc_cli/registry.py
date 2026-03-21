"""Registry class for managing the $AMPLIFIER_HOME filesystem layout."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


class Registry:
    """Manages the Amplifier home directory filesystem layout.

    Handles:
    - Directory structure creation (home/, definitions/, environments/)
    - Alias tracking in agents.yaml and behaviors.yaml
    - Definition file registration with optional source metadata
    """

    def __init__(self, home: Optional[Path] = None) -> None:
        """Initialize the Registry with an optional home directory.

        Args:
            home: Path to use as AMPLIFIER_HOME. Falls back to the
                  AMPLIFIER_HOME environment variable, then ~/.amplifier.
        """
        if home is not None:
            self.home = home
        elif "AMPLIFIER_HOME" in os.environ:
            self.home = Path(os.environ["AMPLIFIER_HOME"])
        else:
            self.home = Path.home() / ".amplifier"

    def ensure_home(self) -> None:
        """Create the home directory structure if it does not already exist.

        Creates:
        - home/             (the root AMPLIFIER_HOME directory)
        - home/definitions/ (stores definition YAML files)
        - home/environments/ (stores environment configs)
        - home/agents.yaml  (alias → definition_id mapping for agents)
        - home/behaviors.yaml (alias → definition_id mapping for behaviors)

        Alias files are initialized with '{}' if they don't exist.
        Idempotent: safe to call multiple times.
        """
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "definitions").mkdir(exist_ok=True)
        (self.home / "environments").mkdir(exist_ok=True)

        agents_yaml = self.home / "agents.yaml"
        if not agents_yaml.exists():
            agents_yaml.write_text("{}\n")

        behaviors_yaml = self.home / "behaviors.yaml"
        if not behaviors_yaml.exists():
            behaviors_yaml.write_text("{}\n")

    def register_definition(
        self, yaml_content: str, source_url: Optional[str] = None
    ) -> str:
        """Register a definition from YAML content.

        Parses the YAML, computes a definition ID, writes the definition to
        definitions/<id>.yaml, and updates the appropriate alias file.

        Args:
            yaml_content: Raw YAML string containing the definition.
            source_url: Optional URL where the definition was fetched from.
                        If provided, a ``_meta`` block is added to the stored
                        file with source_url, source_hash (sha256:<hex>), and
                        fetched_at (ISO timestamp).

        Returns:
            The computed definition_id: '<type>_<local_ref>_<uuid_first_8>'.

        Raises:
            ValueError: If required fields (type, local_ref, uuid) are missing.
        """
        parsed = yaml.safe_load(yaml_content)
        if not isinstance(parsed, dict):
            raise ValueError("YAML content must be a mapping")

        def_type = parsed.get("type")
        local_ref = parsed.get("local_ref")
        uuid_value = parsed.get("uuid")

        if not def_type or not local_ref or not uuid_value:
            raise ValueError(
                "YAML content must contain 'type', 'local_ref', and 'uuid' fields"
            )

        uuid_first_8 = str(uuid_value)[:8]
        definition_id = f"{def_type}_{local_ref}_{uuid_first_8}"

        # Build the data to store (copy original + optional _meta)
        stored_data = dict(parsed)
        if source_url is not None:
            content_bytes = yaml_content.encode("utf-8")
            sha256_hex = hashlib.sha256(content_bytes).hexdigest()
            stored_data["_meta"] = {
                "source_url": source_url,
                "source_hash": f"sha256:{sha256_hex}",
                "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            }

        # Write definition file
        def_file = self.home / "definitions" / f"{definition_id}.yaml"
        def_file.write_text(yaml.dump(stored_data, default_flow_style=False))

        # Update alias file
        if def_type == "agent":
            alias_file = self.home / "agents.yaml"
        else:
            alias_file = self.home / "behaviors.yaml"

        alias_data = yaml.safe_load(alias_file.read_text()) or {}
        alias_data[local_ref] = definition_id
        alias_file.write_text(yaml.dump(alias_data, default_flow_style=False))

        return definition_id
