#!/usr/bin/env python3
"""
Swarm Suite: pip → uv migration script.

Kills running MCP server processes, removes pip artifacts,
installs everything via uv tool, and verifies the result.

Usage:
    python scripts/migrate-to-uv.py             # run migration
    python scripts/migrate-to-uv.py --dry-run    # preview only
    python scripts/migrate-to-uv.py --cleanup     # only clean artifacts, no install
    python scripts/migrate-to-uv.py --doctor      # diagnose issues
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── Package registry ────────────────────────────────────────────────────────

PACKAGES = {
    # pip_name -> (exe_name, pypi_name_for_uv)
    "review-swarm":  ("review-swarm",  "review-swarm"),
    "swarm-kb":      ("swarm-kb",      "swarm-kb"),
    "arch-swarm-ai": ("arch-swarm",    "arch-swarm-ai"),
    "doc-swarm-ai":  ("doc-swarm",     "doc-swarm-ai"),
    "fix-swarm-ai":  ("fix-swarm",     "fix-swarm-ai"),
    "spec-swarm-ai": ("spec-swarm",    "spec-swarm-ai"),
}

IS_WINDOWS = platform.system() == "Windows"


# ── Helpers ─────────────────────────────────────────────────────────────────

class Logger:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def info(self, msg: str):
        print(f"  [INFO]  {msg}")

    def action(self, msg: str):
        tag = "[DRY-RUN]" if self.dry_run else "[ACTION]"
        print(f"  {tag} {msg}")

    def warn(self, msg: str):
        print(f"  [WARN]  {msg}")

    def ok(self, msg: str):
        print(f"  [ OK ]  {msg}")

    def fail(self, msg: str):
        print(f"  [FAIL]  {msg}")

    def header(self, msg: str):
        print(f"\n{'='*60}\n  {msg}\n{'='*60}")


log = Logger()


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a subprocess, print the command, handle errors."""
    log.action(f"$ {' '.join(cmd)}")
    if log.dry_run:
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


def find_python_dirs() -> list[Path]:
    """Find Python site-packages and Scripts dirs on Windows."""
    dirs = []
    if not IS_WINDOWS:
        return dirs
    home = Path.home()
    # System Python install
    for base in [
        home / "AppData" / "Local" / "Programs" / "Python",
        Path("C:/Python"),
    ]:
        if base.exists():
            for pydir in sorted(base.iterdir()):
                if pydir.is_dir() and pydir.name.startswith("Python"):
                    dirs.append(pydir)
    return dirs


def find_site_packages() -> list[Path]:
    """Find all site-packages directories that may contain swarm packages."""
    result = []
    if IS_WINDOWS:
        home = Path.home()
        for pydir in find_python_dirs():
            sp = pydir / "Lib" / "site-packages"
            if sp.exists():
                result.append(sp)
        # User site-packages
        for roaming in [home / "AppData" / "Roaming" / "Python"]:
            if roaming.exists():
                for pydir in sorted(roaming.iterdir()):
                    sp = pydir / "site-packages"
                    if sp.exists():
                        result.append(sp)
    else:
        # Unix: use the current Python's site-packages
        import site
        result.extend(Path(p) for p in site.getsitepackages() if Path(p).exists())
        user_sp = Path(site.getusersitepackages())
        if user_sp.exists():
            result.append(user_sp)
    return result


def find_scripts_dirs() -> list[Path]:
    """Find Scripts/ directories that may contain stale exe shims."""
    result = []
    if IS_WINDOWS:
        for pydir in find_python_dirs():
            scripts = pydir / "Scripts"
            if scripts.exists():
                result.append(scripts)
    return result


# ── Steps ───────────────────────────────────────────────────────────────────

def step_kill_processes():
    """Kill running MCP server processes."""
    log.header("Step 1: Kill running MCP server processes")

    exe_names = [exe for exe, _ in PACKAGES.values()]
    if IS_WINDOWS:
        exe_names = [f"{name}.exe" for name in exe_names]

    killed = 0
    for exe in exe_names:
        if IS_WINDOWS:
            result = run(
                ["taskkill", "/F", "/IM", exe],
                check=False, capture=True,
            )
            if not log.dry_run and result.returncode == 0:
                killed += 1
                log.ok(f"Killed {exe}")
        else:
            result = run(
                ["pkill", "-f", exe.replace(".exe", "")],
                check=False, capture=True,
            )
            if not log.dry_run and result.returncode == 0:
                killed += 1
                log.ok(f"Killed {exe}")

    if killed == 0:
        log.info("No running swarm processes found.")
    else:
        log.info(f"Killed {killed} process group(s).")


def step_pip_uninstall():
    """Uninstall all packages via pip (both passes for dual installs)."""
    log.header("Step 2: Uninstall via pip")

    pip_names = list(PACKAGES.keys())
    for pass_num in (1, 2):
        log.info(f"pip uninstall pass {pass_num}/2")
        run(
            [sys.executable, "-m", "pip", "uninstall", "-y"] + pip_names,
            check=False, capture=True,
        )


def step_clean_exe_shims():
    """Remove stale exe shims from Python Scripts/ directories."""
    log.header("Step 3: Clean stale exe shims")

    scripts_dirs = find_scripts_dirs()
    if not scripts_dirs:
        log.info("No Scripts/ directories found (non-Windows or no system Python).")
        return

    exe_names = [exe for exe, _ in PACKAGES.values()]
    removed = 0

    for scripts_dir in scripts_dirs:
        for exe_name in exe_names:
            for pattern in [f"{exe_name}*", f"{exe_name}.exe"]:
                for match in scripts_dir.glob(pattern):
                    log.action(f"rm {match}")
                    if not log.dry_run:
                        try:
                            match.unlink()
                            removed += 1
                            log.ok(f"Removed {match}")
                        except PermissionError:
                            log.warn(f"Cannot remove {match} (locked). Try closing Claude Code first.")
                        except OSError as e:
                            log.warn(f"Cannot remove {match}: {e}")

    log.info(f"Removed {removed} stale exe shim(s)." if removed else "No stale exe shims found.")


def step_clean_tilde_dirs():
    """Remove leftover ~ directories from site-packages."""
    log.header("Step 4: Clean ~ directories from site-packages")

    # Known module names (underscored) that could appear as ~<partial>
    known_modules = [
        "review_swarm", "swarm_kb", "arch_swarm", "doc_swarm",
        "fix_swarm", "spec_swarm",
    ]

    removed = 0
    for sp in find_site_packages():
        for entry in sp.iterdir():
            if not entry.name.startswith("~"):
                continue
            # Check if it looks like one of our packages
            name_lower = entry.name.lower()
            is_ours = any(mod in name_lower for mod in known_modules)
            if not is_ours:
                # Also match ~eview_swarm, ~warm_kb etc (first char stripped)
                stripped = entry.name[1:]  # remove ~
                is_ours = any(
                    stripped.lower().startswith(mod[1:]) or mod.startswith(stripped.lower())
                    for mod in known_modules
                )
            if is_ours:
                log.action(f"rmtree {entry}")
                if not log.dry_run:
                    try:
                        shutil.rmtree(entry)
                        removed += 1
                        log.ok(f"Removed {entry}")
                    except OSError as e:
                        log.warn(f"Cannot remove {entry}: {e}")

    log.info(f"Removed {removed} leftover ~ dir(s)." if removed else "No ~ directories found.")


def step_clean_dist_info():
    """Remove leftover .dist-info directories from site-packages."""
    log.header("Step 5: Clean leftover .dist-info directories")

    known_dist_prefixes = [
        "review_swarm-", "swarm_kb-", "arch_swarm", "doc_swarm",
        "fix_swarm", "spec_swarm",
    ]

    removed = 0
    for sp in find_site_packages():
        for entry in sp.iterdir():
            if not entry.name.endswith(".dist-info"):
                continue
            name_lower = entry.name.lower()
            is_ours = any(name_lower.startswith(prefix) for prefix in known_dist_prefixes)
            if is_ours:
                log.action(f"rmtree {entry}")
                if not log.dry_run:
                    try:
                        shutil.rmtree(entry)
                        removed += 1
                        log.ok(f"Removed {entry}")
                    except OSError as e:
                        log.warn(f"Cannot remove {entry}: {e}")

    log.info(f"Removed {removed} dist-info dir(s)." if removed else "No leftover dist-info found.")


def step_uv_install():
    """Install all packages via uv tool install."""
    log.header("Step 6: Install via uv")

    uv = shutil.which("uv")
    if not uv:
        log.fail("uv not found in PATH. Install it first: https://docs.astral.sh/uv/getting-started/installation/")
        sys.exit(1)

    pypi_names = [pypi for _, pypi in PACKAGES.values()]
    run([uv, "tool", "install"] + pypi_names, check=False)


def step_verify():
    """Verify that all packages are installed and accessible."""
    log.header("Step 7: Verify installation")

    all_ok = True
    for pip_name, (exe_name, _) in PACKAGES.items():
        exe_path = shutil.which(exe_name)
        if exe_path:
            # Check it points to uv's bin, not pip's Scripts
            if IS_WINDOWS and "Scripts" in exe_path and "Python3" in exe_path:
                log.warn(f"{exe_name} -> {exe_path} (still points to pip Scripts!)")
                all_ok = False
            else:
                log.ok(f"{exe_name} -> {exe_path}")
        else:
            log.fail(f"{exe_name} not found in PATH")
            all_ok = False

    if all_ok:
        log.info("All packages verified successfully.")
    else:
        log.warn("Some packages have issues. Check the output above.")

    return all_ok


def step_doctor():
    """Diagnose common installation issues."""
    log.header("Doctor: Diagnosing installation")

    # 1. Check uv
    uv = shutil.which("uv")
    if uv:
        log.ok(f"uv found: {uv}")
    else:
        log.fail("uv not found in PATH")

    # 2. Check each exe
    for pip_name, (exe_name, _) in PACKAGES.items():
        exe_path = shutil.which(exe_name)
        if exe_path:
            log.ok(f"{exe_name} -> {exe_path}")
        else:
            log.warn(f"{exe_name} not found")

    # 3. Check for PATH shadowing
    if IS_WINDOWS:
        log.info("Checking for PATH shadowing...")
        scripts_dirs = find_scripts_dirs()
        for scripts_dir in scripts_dirs:
            for exe_name, _ in PACKAGES.values():
                stale = scripts_dir / f"{exe_name}.exe"
                if stale.exists():
                    log.warn(f"Stale exe: {stale} (may shadow uv install)")

    # 4. Check for dual site-packages installs
    log.info("Checking for leftover packages in site-packages...")
    known_modules = ["review_swarm", "swarm_kb", "arch_swarm", "doc_swarm", "fix_swarm", "spec_swarm"]
    for sp in find_site_packages():
        for mod in known_modules:
            mod_dir = sp / mod
            if mod_dir.exists():
                log.warn(f"Leftover module: {mod_dir}")

    # 5. Check for ~ dirs
    log.info("Checking for ~ garbage directories...")
    for sp in find_site_packages():
        for entry in sp.iterdir():
            if entry.name.startswith("~") and any(
                m in entry.name.lower() for m in ["swarm", "review", "arch", "doc", "fix", "spec"]
            ):
                log.warn(f"Garbage dir: {entry}")

    # 6. Check for running processes
    if IS_WINDOWS:
        log.info("Checking for running swarm processes...")
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq review-swarm.exe"],
            capture_output=True, text=True, check=False,
        )
        if "review-swarm.exe" in result.stdout:
            log.warn("review-swarm.exe is running (will block upgrades)")
        # Check others too
        for exe_name, _ in PACKAGES.values():
            if exe_name == "review-swarm":
                continue
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe_name}.exe"],
                capture_output=True, text=True, check=False,
            )
            if f"{exe_name}.exe" in result.stdout:
                log.warn(f"{exe_name}.exe is running (will block upgrades)")

    log.info("Doctor complete.")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Swarm Suite: pip -> uv migration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without executing")
    parser.add_argument("--cleanup", action="store_true", help="Only clean artifacts, don't install")
    parser.add_argument("--doctor", action="store_true", help="Diagnose installation issues")
    args = parser.parse_args()

    log.dry_run = args.dry_run

    if args.dry_run:
        print("\n  *** DRY RUN — no changes will be made ***\n")

    if args.doctor:
        step_doctor()
        return

    step_kill_processes()
    step_pip_uninstall()
    step_clean_exe_shims()
    step_clean_tilde_dirs()
    step_clean_dist_info()

    if not args.cleanup:
        step_uv_install()

    step_verify()

    print("\nDone.")


if __name__ == "__main__":
    main()
