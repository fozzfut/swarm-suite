"""Enforce import-direction rules across the Swarm Suite monorepo.

Layer rules (from CLAUDE.md):

    swarm_core    -- may import from stdlib + (mcp, pyyaml, click)
    swarm_kb      -- may import from swarm_core + stdlib + vendor
    *_swarm       -- may import from swarm_core, swarm_kb, vendor
                     -- MUST NOT import from each other

Detects with `ast.parse` -- no full imports needed; runs in seconds.

Exit code 0 = clean, 1 = violations (prints them).

Run from repo root:
    python scripts/check_imports.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_ROOT = REPO_ROOT / "packages"

# Map package directory name -> top-level Python module name.
PKG_TO_MODULE: dict[str, str] = {
    "swarm-core": "swarm_core",
    "swarm-kb": "swarm_kb",
    "spec-swarm": "spec_swarm",
    "arch-swarm": "arch_swarm",
    "review-swarm": "review_swarm",
    "fix-swarm": "fix_swarm",
    "doc-swarm": "doc_swarm",
}

# What each module is allowed to import from (other in-suite modules only).
ALLOWED: dict[str, set[str]] = {
    "swarm_core": set(),
    "swarm_kb": {"swarm_core"},
    "spec_swarm": {"swarm_core", "swarm_kb"},
    "arch_swarm": {"swarm_core", "swarm_kb"},
    "review_swarm": {"swarm_core", "swarm_kb"},
    "fix_swarm": {"swarm_core", "swarm_kb"},
    "doc_swarm": {"swarm_core", "swarm_kb"},
}

ALL_SUITE_MODULES = set(ALLOWED.keys())

# Grandfathered violations -- known to be wrong, scheduled for migration.
# Format: {(importer_module, imported_module): [relative_path_from_repo, ...]}
# Migration plan tracked in docs/decisions/. New entries here require a
# corresponding decision doc URL in the comment.
GRANDFATHERED: dict[tuple[str, str], set[str]] = {
    # 2026-04-26-fix-swarm-arch-coupling.md: RESOLVED on 2026-04-26.
    # code_scanner extracted to swarm_core.code_scan; arch_swarm now ships a
    # shim. fix_swarm.arch_adapter imports from swarm_core directly.
}


class Violation:
    __slots__ = ("file", "line", "importer", "imported")

    def __init__(self, file: Path, line: int, importer: str, imported: str) -> None:
        self.file = file
        self.line = line
        self.importer = importer
        self.imported = imported

    def __str__(self) -> str:
        rel = self.file.relative_to(REPO_ROOT)
        return f"{rel}:{self.line}: {self.importer} imports {self.imported} (forbidden)"


def imports_in(path: Path) -> list[tuple[int, str]]:
    """Return [(line, top_level_module), ...] for every import in `path`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name.split(".", 1)[0]))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                continue
            module = node.module or ""
            out.append((node.lineno, module.split(".", 1)[0]))
    return out


def check_file(path: Path, importer_module: str) -> list[Violation]:
    allowed = ALLOWED.get(importer_module, set())
    rel = path.relative_to(REPO_ROOT).as_posix()
    out: list[Violation] = []
    for line, mod in imports_in(path):
        if mod in ALL_SUITE_MODULES and mod != importer_module and mod not in allowed:
            grandfathered = GRANDFATHERED.get((importer_module, mod), set())
            if rel in grandfathered:
                continue
            out.append(Violation(path, line, importer_module, mod))
    return out


def check_package(pkg_dir: Path, importer_module: str) -> list[Violation]:
    src_dir = pkg_dir / "src" / importer_module
    if not src_dir.is_dir():
        return []
    out: list[Violation] = []
    for py_file in src_dir.rglob("*.py"):
        out.extend(check_file(py_file, importer_module))
    return out


def main() -> int:
    if not PACKAGES_ROOT.is_dir():
        print(f"packages/ not found at {PACKAGES_ROOT}", file=sys.stderr)
        return 2

    violations: list[Violation] = []
    for pkg_name, module_name in PKG_TO_MODULE.items():
        pkg_dir = PACKAGES_ROOT / pkg_name
        if not pkg_dir.is_dir():
            continue
        violations.extend(check_package(pkg_dir, module_name))

    if not violations:
        print(f"check_imports: OK ({len(PKG_TO_MODULE)} packages scanned)")
        return 0

    print(f"check_imports: {len(violations)} violation(s)\n")
    for v in violations:
        print(str(v))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
