"""Stack adapters: per-language test-command detection for run_tests.

Each adapter is a YAML file in ``stacks/`` declaring how to detect the
stack (which files indicate it) and how to run its test suite. Drop a
new YAML file to add a new stack — no code changes.

Niche-driven: instrument / installation software is not Python-only.
Embedded firmware is C/C++/Rust; lab/SCADA tooling is often a mix of
Python + Node + Go. spec-side analysis (datasheet → registers/pins/
protocols/timing) is already language-agnostic; this module closes
the same gap on the runtime side.

Per-file syntax checking remains Python-only (see
``regression_checker.check_syntax``) — non-Python stacks rely on the
test-command's compiler stage to surface syntax errors. That's an
honest limitation; building a fast per-file syntax checker for every
language in scope is out of scope here.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_log = logging.getLogger("fix_swarm.stack_registry")

_BUILTIN_DIR = Path(__file__).parent / "stacks"


@dataclass
class StackAdapter:
    """A single language/build-system adapter.

    YAML files MAY carry additional documentation fields (``description``,
    ``file_extensions``) — the loader silently ignores them. Add the fields
    here only when code actually consumes them.
    """

    name: str
    detect_files: list[str] = field(default_factory=list)
    detect_globs: list[str] = field(default_factory=list)
    test_command: str = ""

    def matches(self, base_dir: Path) -> bool:
        for f in self.detect_files:
            if (base_dir / f).exists():
                return True
        for g in self.detect_globs:
            if any(base_dir.glob(g)):
                return True
        return False

    def resolved_command(self) -> str:
        """Replace placeholders in test_command with runtime values."""
        return self.test_command.replace("{python}", sys.executable)


class StackRegistry:
    """Loads stack adapters from one or more YAML directories."""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        custom_dirs: list[Path] | None = None,
    ) -> None:
        self._adapters: dict[str, StackAdapter] = {}
        for d in [builtin_dir if builtin_dir is not None else _BUILTIN_DIR,
                  *(custom_dirs or [])]:
            if d and d.is_dir():
                self._load_dir(d)

    def _load_dir(self, d: Path) -> None:
        for y in sorted(d.glob("*.yaml")):
            try:
                data = yaml.safe_load(y.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                _log.warning("Skipping malformed stack %s: %s", y, exc)
                continue
            if not isinstance(data, dict):
                _log.warning("Skipping non-mapping stack %s", y)
                continue
            name = str(data.get("name") or y.stem)
            adapter = StackAdapter(
                name=name,
                detect_files=[str(x) for x in (data.get("detect_files") or [])],
                detect_globs=[str(x) for x in (data.get("detect_globs") or [])],
                test_command=str(data.get("test_command") or ""),
            )
            # Custom dirs override builtin by name.
            self._adapters[adapter.name] = adapter

    def all(self) -> list[StackAdapter]:
        return list(self._adapters.values())

    def get(self, name: str) -> StackAdapter | None:
        return self._adapters.get(name)

    def detect(self, base_dir: Path) -> StackAdapter | None:
        """Return the first matching adapter, or None."""
        for a in self._adapters.values():
            if a.matches(base_dir):
                return a
        return None

    def detect_test_command(self, base_dir: Path) -> str:
        """Convenience: return the resolved test command, or empty string."""
        a = self.detect(base_dir)
        return a.resolved_command() if a is not None else ""
