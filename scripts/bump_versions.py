"""Bump versions across all packages with a compatibility check.

Each package keeps its own version (PyPI compatibility). This script
edits every `pyproject.toml` so they stay in sync where they should:

  - swarm-core's version is the floor that all others depend on.
  - When `swarm-core` bumps (minor or major), other packages MUST bump
    their `swarm-core>=` constraint accordingly.
  - swarm-kb's version is the floor for the five tool packages.

Usage:
    python scripts/bump_versions.py --package swarm-core --new-version 0.2.0
    python scripts/bump_versions.py --all-patch              # bump all .Z
    python scripts/bump_versions.py --check                  # report mismatches

The script edits pyproject.toml literals; it does NOT run `pip install`,
publish, or commit. Caller does that.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_ROOT = REPO_ROOT / "packages"

VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
DEP_RE_TMPL = r'"({pkg})>=([0-9]+(?:\.[0-9]+){{0,2}})"'


def read_version(pyproject: Path) -> str | None:
    text = pyproject.read_text(encoding="utf-8")
    m = VERSION_RE.search(text)
    return m.group(1) if m else None


def write_version(pyproject: Path, new: str) -> None:
    text = pyproject.read_text(encoding="utf-8")
    text2 = VERSION_RE.sub(f'version = "{new}"', text, count=1)
    pyproject.write_text(text2, encoding="utf-8")


def list_packages() -> dict[str, Path]:
    return {
        d.name: d / "pyproject.toml"
        for d in sorted(PACKAGES_ROOT.iterdir())
        if (d / "pyproject.toml").is_file()
    }


def bump_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"cannot patch-bump non-semver: {version}")
    parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


def cmd_check(packages: dict[str, Path]) -> int:
    print("Current versions:")
    for name, py in packages.items():
        v = read_version(py)
        print(f"  {name:<14} {v}")
    return 0


def cmd_bump_one(packages: dict[str, Path], pkg: str, new: str) -> int:
    if pkg not in packages:
        print(f"unknown package: {pkg}", file=sys.stderr)
        return 1
    write_version(packages[pkg], new)
    print(f"{pkg} -> {new}")
    return 0


def cmd_all_patch(packages: dict[str, Path]) -> int:
    for name, py in packages.items():
        v = read_version(py)
        if not v:
            print(f"  [skip] {name} (no version)")
            continue
        new = bump_patch(v)
        write_version(py, new)
        print(f"  {name}: {v} -> {new}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--all-patch", action="store_true")
    parser.add_argument("--package")
    parser.add_argument("--new-version")
    args = parser.parse_args()

    packages = list_packages()
    if not packages:
        print("no packages found", file=sys.stderr)
        return 2

    if args.check:
        return cmd_check(packages)
    if args.all_patch:
        return cmd_all_patch(packages)
    if args.package and args.new_version:
        return cmd_bump_one(packages, args.package, args.new_version)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
