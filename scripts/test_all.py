"""Run pytest against every package in sequence.

Pytest's rootdir / conftest plugin-naming collides when multiple
`packages/<name>/tests/conftest.py` are loaded in one invocation
(each registers as `tests.conftest`). Running them sequentially -- one
process per package -- is the simplest workaround.

The root `conftest.py` (at the repo root) injects every package's `src/`
into sys.path so editable installs are not required.

Usage:
    python scripts/test_all.py [-q | -v | --tb=short ...]

Any extra args are forwarded to pytest. Exit code is non-zero if any
package's suite fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = (
    "swarm-core", "swarm-kb",
    "spec-swarm", "arch-swarm", "review-swarm", "fix-swarm", "doc-swarm",
)


def _build_pythonpath() -> str:
    """Concatenate every package's src/ for cross-package imports."""
    parts = [str(REPO_ROOT / "packages" / p / "src") for p in PACKAGES]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def main() -> int:
    extra = sys.argv[1:] or ["-q", "--tb=short"]
    failed: list[str] = []
    totals = {"passed": 0, "failed": 0}

    for pkg in PACKAGES:
        tests_dir = REPO_ROOT / "packages" / pkg / "tests"
        if not tests_dir.is_dir():
            print(f"=== {pkg}: no tests dir, skipping ===")
            continue
        print(f"\n=== {pkg} ===")
        # PYTHONPATH carries every package's src/ so cross-package
        # imports (review-swarm tests use swarm_core, etc.) just work
        # without an editable install.
        cmd = [sys.executable, "-m", "pytest", str(tests_dir), *extra]
        env = {**os.environ, "PYTHONPATH": _build_pythonpath()}
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
        if result.returncode != 0:
            failed.append(pkg)

    print()
    if failed:
        print(f"FAILED packages: {', '.join(failed)}")
        return 1
    print("All packages green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
