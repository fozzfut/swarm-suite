"""Publish every package in dependency order.

Monorepo-aware version of the manual `for pkg in ...; cd packages/$pkg; ...`
loop. Builds each package, runs `twine check`, then `twine upload` in
dependency order so PyPI always knows about a dep before its consumers.

Default behavior (no flags):
    1. Pre-flight: scripts/verify_e2e.py --quick (47 checks)
    2. Build every packages/<name>/ via `python -m build`
    3. `twine check` every artifact
    4. `twine upload` in dep order: swarm-core -> swarm-kb -> tools

Flags:
    --testpypi               upload to TestPyPI instead of real PyPI
    --repository <name>      use a custom .pypirc section
                             (e.g. `pypi-bootstrap` for first-time
                             account-wide publishes)
    --skip-build             reuse existing dist/ artifacts
    --skip-verify            skip the pre-flight verify_e2e
    --skip-upload            build + check only, no upload
    --packages <a,b,c>       publish only a subset (in given order)

Examples:
    # First-time publish of swarm-core with a temporary account-wide token
    python scripts/publish_all.py --packages swarm-core --repository pypi-bootstrap

    # TestPyPI dry-run for everything
    python scripts/publish_all.py --testpypi

    # Real publish, all packages, default token in ~/.pypirc
    python scripts/publish_all.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Strict dependency order. Foundation first; tools last (any order
# among themselves, but kept stable for predictable output).
DEFAULT_PUBLISH_ORDER = (
    "swarm-core",
    "swarm-kb",
    "spec-swarm",
    "arch-swarm",
    "review-swarm",
    "fix-swarm",
    "doc-swarm",
)

# Wait between dep and consumer publishes so PyPI's index updates
# before pip resolver tries to find the dep.
DEP_PROPAGATION_SECONDS = 30


def run(cmd: list[str], *, cwd: Path = REPO_ROOT, check: bool = True) -> int:
    print(f"  $ {' '.join(cmd)}")
    rc = subprocess.run(cmd, cwd=str(cwd)).returncode
    if check and rc != 0:
        sys.exit(f"FAILED: {' '.join(cmd)} -> rc={rc}")
    return rc


def clean_dist(pkg: str) -> None:
    pkg_dir = REPO_ROOT / "packages" / pkg
    for sub in ("dist", "build"):
        d = pkg_dir / sub
        if d.exists():
            shutil.rmtree(d)
    for egg in pkg_dir.glob("*.egg-info"):
        shutil.rmtree(egg)
    for egg in (pkg_dir / "src").glob("*.egg-info"):
        shutil.rmtree(egg)


def build_package(pkg: str) -> None:
    pkg_dir = REPO_ROOT / "packages" / pkg
    if not pkg_dir.is_dir():
        sys.exit(f"package dir not found: {pkg_dir}")
    print(f"\n=== build {pkg} ===")
    clean_dist(pkg)
    run([sys.executable, "-m", "build"], cwd=pkg_dir)


def check_artifacts(pkg: str) -> None:
    pkg_dir = REPO_ROOT / "packages" / pkg
    dist = pkg_dir / "dist"
    artifacts = sorted(dist.glob("*"))
    if not artifacts:
        sys.exit(f"no artifacts in {dist}")
    print(f"\n=== twine check {pkg} ({len(artifacts)} artifact(s)) ===")
    run([sys.executable, "-m", "twine", "check", *map(str, artifacts)])


def upload_package(pkg: str, *, repository: str | None = None,
                    testpypi: bool = False) -> None:
    pkg_dir = REPO_ROOT / "packages" / pkg
    artifacts = sorted((pkg_dir / "dist").glob("*"))
    cmd = [sys.executable, "-m", "twine", "upload"]
    if testpypi:
        cmd += ["--repository", "testpypi"]
    elif repository:
        cmd += ["--repository", repository]
    cmd += [str(a) for a in artifacts]
    print(f"\n=== upload {pkg} ===")
    run(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--testpypi", action="store_true",
                        help="Upload to TestPyPI instead of real PyPI.")
    parser.add_argument("--repository",
                        help="Custom .pypirc section name (e.g. pypi-bootstrap).")
    parser.add_argument("--skip-build", action="store_true",
                        help="Reuse existing dist/ artifacts.")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip pre-flight verify_e2e.py.")
    parser.add_argument("--skip-upload", action="store_true",
                        help="Build + check only.")
    parser.add_argument("--packages",
                        help="Comma-separated subset (in publish order). "
                             "Default: every package.")
    args = parser.parse_args()

    if args.testpypi and args.repository:
        sys.exit("--testpypi and --repository are mutually exclusive")

    packages = (
        [p.strip() for p in args.packages.split(",") if p.strip()]
        if args.packages else list(DEFAULT_PUBLISH_ORDER)
    )

    # 1. Pre-flight
    if not args.skip_verify:
        print("=== pre-flight: verify_e2e --quick ===")
        run([sys.executable, "scripts/verify_e2e.py", "--quick"])

    # 2. Build
    if not args.skip_build:
        for pkg in packages:
            build_package(pkg)

    # 3. Check
    for pkg in packages:
        check_artifacts(pkg)

    if args.skip_upload:
        print("\n--skip-upload: build + check complete; not publishing.")
        return 0

    # 4. Upload in order, with delay between dep and consumer
    print("\n=== uploading ===")
    last_was_dep = False
    for pkg in packages:
        if last_was_dep:
            print(f"  sleeping {DEP_PROPAGATION_SECONDS}s for PyPI index propagation...")
            time.sleep(DEP_PROPAGATION_SECONDS)
        upload_package(pkg, repository=args.repository, testpypi=args.testpypi)
        # swarm-core and swarm-kb are deps of subsequent packages
        last_was_dep = pkg in ("swarm-core", "swarm-kb")

    print("\n=== done ===")
    print("Verify with `pip install --upgrade <pkg>` in a clean venv.")
    print("If everything works, drop the 'publish pending' notice from README.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
