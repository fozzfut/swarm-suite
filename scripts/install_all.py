"""Editable-install every package in dependency order.

Run from repo root:
    python scripts/install_all.py
    python scripts/install_all.py --no-deps   # skip pip resolver
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_ROOT = REPO_ROOT / "packages"

# Order matches the dependency DAG -- core first, kb next, tools last.
INSTALL_ORDER = (
    "swarm-core",
    "swarm-kb",
    "spec-swarm",
    "arch-swarm",
    "review-swarm",
    "fix-swarm",
    "doc-swarm",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-deps", action="store_true",
                        help="Pass --no-deps to pip (faster, skips resolver).")
    args = parser.parse_args()

    failures: list[str] = []
    for pkg in INSTALL_ORDER:
        pkg_dir = PACKAGES_ROOT / pkg
        if not pkg_dir.is_dir():
            print(f"  [skip] {pkg} (not present)")
            continue
        cmd = [sys.executable, "-m", "pip", "install", "-e", str(pkg_dir), "--quiet"]
        if args.no_deps:
            cmd.append("--no-deps")
        print(f"=== installing {pkg} ===")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failures.append(pkg)

    if failures:
        print(f"\nFAILED: {', '.join(failures)}")
        return 1
    print("\nAll packages installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
