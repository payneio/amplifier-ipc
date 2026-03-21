"""
Safety validation module for the Amplifier bash tool.

Provides a configurable, profile-based safety system with smart pattern matching
that avoids false positives while maintaining security for dangerous commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class BlockPattern:
    """A pattern to match against commands for blocking."""

    pattern: str
    reason: str
    check_type: Literal["command", "substring", "regex"] = "substring"


@dataclass
class SafetyProfile:
    """A safety profile defining blocked patterns and override behavior."""

    name: str
    blocked_patterns: list[BlockPattern]
    allow_overrides: bool = False


@dataclass
class SafetyResult:
    """Result of a safety validation check."""

    allowed: bool
    reason: str | None = None
    matched_pattern: str | None = None
    hint: str | None = None


@dataclass
class SafetyConfig:
    """Configuration for safety validation."""

    profile: str = "strict"
    allowed_commands: list[str] = field(default_factory=list)
    denied_commands: list[str] = field(default_factory=list)
    safety_overrides: dict | None = None


STRICT_PROFILE = SafetyProfile(
    name="strict",
    blocked_patterns=[
        BlockPattern("rm -rf /", "Prevents root filesystem deletion", "command"),
        BlockPattern("rm -rf ~", "Prevents home directory deletion", "command"),
        BlockPattern("rm -fr /", "Prevents root filesystem deletion", "command"),
        BlockPattern("rm -fr ~", "Prevents home directory deletion", "command"),
        BlockPattern(
            "sudo", "Privilege escalation not allowed in strict mode", "command"
        ),
        BlockPattern("su -", "User switching not allowed", "command"),
        BlockPattern("dd if=/dev/zero", "Dangerous disk overwrite", "substring"),
        BlockPattern("dd if=/dev/random", "Dangerous disk overwrite", "substring"),
        BlockPattern("mkfs", "Filesystem creation not allowed", "command"),
        BlockPattern(r">\s*/dev/(?!null)", "Writing to devices not allowed", "regex"),
        BlockPattern("passwd", "Password changes not allowed", "command"),
        BlockPattern("chmod 777 /", "Dangerous root permissions", "substring"),
        BlockPattern(
            "chown -R /", "Recursive ownership of root not allowed", "substring"
        ),
        BlockPattern(":(){ :|:& };:", "Fork bomb", "substring"),
    ],
    allow_overrides=False,
)

STANDARD_PROFILE = SafetyProfile(
    name="standard",
    blocked_patterns=[
        BlockPattern("rm -rf /", "Prevents root filesystem deletion", "command"),
        BlockPattern("rm -rf ~", "Prevents home directory deletion", "command"),
        BlockPattern("rm -fr /", "Prevents root filesystem deletion", "command"),
        BlockPattern("rm -fr ~", "Prevents home directory deletion", "command"),
        BlockPattern(
            "sudo", "Privilege escalation not allowed in standard mode", "command"
        ),
        BlockPattern("su -", "User switching not allowed", "command"),
        BlockPattern("dd if=/dev/zero", "Dangerous disk overwrite", "substring"),
        BlockPattern("dd if=/dev/random", "Dangerous disk overwrite", "substring"),
        BlockPattern("mkfs", "Filesystem creation not allowed", "command"),
        BlockPattern(r">\s*/dev/(?!null)", "Writing to devices not allowed", "regex"),
        BlockPattern("passwd", "Password changes not allowed", "command"),
        BlockPattern("chmod 777 /", "Dangerous root permissions", "substring"),
        BlockPattern(
            "chown -R /", "Recursive ownership of root not allowed", "substring"
        ),
        BlockPattern(":(){ :|:& };:", "Fork bomb", "substring"),
    ],
    allow_overrides=True,
)

PERMISSIVE_PROFILE = SafetyProfile(
    name="permissive",
    blocked_patterns=[
        BlockPattern("rm -rf /", "Prevents root filesystem deletion", "command"),
        BlockPattern("rm -fr /", "Prevents root filesystem deletion", "command"),
        BlockPattern(":(){ :|:& };:", "Fork bomb", "substring"),
    ],
    allow_overrides=True,
)

UNRESTRICTED_PROFILE = SafetyProfile(
    name="unrestricted",
    blocked_patterns=[],
    allow_overrides=True,
)

PROFILES: dict[str, SafetyProfile] = {
    "strict": STRICT_PROFILE,
    "standard": STANDARD_PROFILE,
    "permissive": PERMISSIVE_PROFILE,
    "unrestricted": UNRESTRICTED_PROFILE,
}


class SafetyValidator:
    """Validates commands against safety rules based on configured profile."""

    def __init__(self, profile: str = "strict", config: SafetyConfig | None = None):
        if profile not in PROFILES:
            valid_profiles = ", ".join(PROFILES.keys())
            raise ValueError(
                f"Unknown profile '{profile}'. Valid profiles: {valid_profiles}"
            )

        self.profile = PROFILES[profile]
        self.config = config or SafetyConfig(profile=profile)

        self.allowed_commands = self.config.allowed_commands
        self.denied_commands = self.config.denied_commands

        self._override_allows: list[str] = []
        self._override_blocks: list[str] = []
        if self.config.safety_overrides:
            self._override_allows = self.config.safety_overrides.get("allow", [])
            self._override_blocks = self.config.safety_overrides.get("block", [])

    def validate(self, command: str) -> SafetyResult:
        """Validate a command against safety rules."""
        if self.profile.name == "unrestricted":
            return SafetyResult(allowed=True)

        if self.profile.allow_overrides:
            if self._matches_allowlist(command):
                return SafetyResult(allowed=True)

        for pattern in self.profile.blocked_patterns:
            if self._check_pattern(command, pattern):
                return SafetyResult(
                    allowed=False,
                    reason=pattern.reason,
                    matched_pattern=pattern.pattern,
                    hint="Use safety_profile: 'permissive' or 'unrestricted' for container/VM environments",
                )

        for denied in self.denied_commands:
            if self._matches_wildcard(command, denied):
                return SafetyResult(
                    allowed=False,
                    reason=f"Matches custom denied pattern: {denied}",
                    matched_pattern=denied,
                    hint="Remove from denied_commands or add to allowed_commands (if profile allows overrides)",
                )

        for block_pattern in self._override_blocks:
            if self._matches_wildcard(command, block_pattern):
                return SafetyResult(
                    allowed=False,
                    reason=f"Blocked by safety_overrides: {block_pattern}",
                    matched_pattern=block_pattern,
                    hint="Remove from safety_overrides.block",
                )

        return SafetyResult(allowed=True)

    def _matches_allowlist(self, command: str) -> bool:
        for pattern in self._override_allows:
            if self._matches_wildcard(command, pattern, substring_fallback=False):
                return True

        for pattern in self.allowed_commands:
            if self._matches_wildcard(command, pattern, substring_fallback=False):
                return True

        return False

    def _matches_wildcard(
        self, command: str, pattern: str, substring_fallback: bool = True
    ) -> bool:
        if command.lower() == pattern.lower():
            return True

        if "*" in pattern:
            regex_pattern = re.escape(pattern).replace(r"\*", ".*")
            regex_pattern = f"^{regex_pattern}$"
            if re.match(regex_pattern, command, re.IGNORECASE):
                return True
        elif substring_fallback:
            if pattern.lower() in command.lower():
                return True

        return False

    def _find_quoted_regions(self, command: str) -> list[tuple[int, int]]:
        regions = []
        i = 0
        while i < len(command):
            if command[i] in ('"', "'"):
                quote_char = command[i]
                start = i
                i += 1
                while i < len(command):
                    if command[i] == "\\" and i + 1 < len(command):
                        i += 2
                        continue
                    if command[i] == quote_char:
                        regions.append((start, i + 1))
                        break
                    i += 1
            i += 1
        return regions

    def _in_quoted_region(self, pos: int, regions: list[tuple[int, int]]) -> bool:
        for start, end in regions:
            if start < pos < end:
                return True
        return False

    def _is_in_command_position(self, command: str, idx: int) -> bool:
        quoted_regions = self._find_quoted_regions(command)
        if self._in_quoted_region(idx, quoted_regions):
            return False

        prefix = command[:idx].strip()
        if not prefix:
            return True

        before = command[:idx].rstrip()
        if not before:
            return True

        command_starters = [";", "|", "&&", "||", "(", "`", "$("]
        for starter in command_starters:
            if before.endswith(starter):
                return True

        if before.endswith("|") and not before.endswith("||"):
            return True

        return False

    def _check_pattern(self, command: str, pattern: BlockPattern) -> bool:
        if pattern.check_type == "substring":
            return self._check_substring(command, pattern.pattern)
        elif pattern.check_type == "command":
            return self._check_command_position(command, pattern.pattern)
        elif pattern.check_type == "regex":
            return self._check_regex(command, pattern.pattern)
        else:
            return self._check_substring(command, pattern.pattern)

    def _check_substring(self, command: str, pattern: str) -> bool:
        return pattern.lower() in command.lower()

    def _check_command_position(self, command: str, pattern: str) -> bool:
        command_lower = command.lower()
        pattern_lower = pattern.lower()

        start = 0
        while True:
            idx = command_lower.find(pattern_lower, start)
            if idx == -1:
                break

            if self._is_in_command_position(command, idx):
                if "/" in pattern:
                    if idx > 0:
                        char_before = command[idx - 1]
                        if char_before not in " \t;|&()>`":
                            start = idx + 1
                            continue

                return True

            start = idx + 1

        return False

    def _check_regex(self, command: str, pattern: str) -> bool:
        try:
            return bool(re.search(pattern, command))
        except re.error:
            return False
