"""Stage 7 Release -- prep for PyPI / GitHub Releases.

Subtools:

| subtool                  | purpose                                            |
|--------------------------|----------------------------------------------------|
| propose_version_bump     | Read git log since last tag, propose patch/minor/major |
| generate_changelog       | Read git log since last tag, draft CHANGELOG.md entry |
| validate_pyproject       | Check pyproject.toml for PyPI-required fields      |
| build_dist               | Run `python -m build`; check `dist/` artifacts     |
| release_summary          | "Ready to twine upload" with explicit checklist    |

NEVER auto-publishes. The user runs `twine upload` themselves; the suite
only PREPARES.

See docs/decisions/2026-04-26-stages-6-7-hardening-release.md for the
contract.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from swarm_core.io import atomic_write_text, append_jsonl_line
from swarm_core.logging_setup import get_logger
from swarm_core.sessions import SessionLifecycle
from swarm_core.timeutil import now_iso

_log = get_logger("kb.release_session")


class ReleaseSessionLifecycle(SessionLifecycle):
    tool_name = "release"
    session_prefix = "release"
    initial_files = ("events.jsonl",)


# ---------------------------------------------------------------- public API


def start_release(sessions_root: Path, *, project_path: str, name: str = "") -> dict:
    lc = ReleaseSessionLifecycle(sessions_root)
    sid = lc.create(project_path=project_path, name=name)
    return {"session_id": sid, "session_dir": str(lc.session_dir(sid))}


def propose_version_bump(sessions_root: Path, *, session_id: str) -> dict:
    """Read git log since last tag; propose patch/minor/major.

    Heuristic:
      - Any commit subject starting with "feat!:" / "fix!:" / "refactor!:" -> major
      - Any commit subject starting with "feat:" -> minor
      - Otherwise -> patch
    """
    lc = ReleaseSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)
    project = Path(_meta(sess_dir)["project_path"])

    last_tag = _git(["describe", "--tags", "--abbrev=0"], cwd=project) or ""
    rng = f"{last_tag}..HEAD" if last_tag else "HEAD"
    log = _git(["log", "--pretty=format:%s", rng], cwd=project) or ""
    subjects = [s.strip() for s in log.splitlines() if s.strip()]

    bump = "patch"
    reason_lines: list[str] = []
    for s in subjects:
        if re.match(r"^(feat|fix|refactor|chore|perf)!:", s):
            bump = "major"
            reason_lines.append(f"breaking: {s}")
            break
        if s.startswith("feat:") and bump == "patch":
            bump = "minor"
            reason_lines.append(f"feature: {s}")

    current = _read_current_version(project)
    proposed = _bump(current, bump) if current else ""

    out = {
        "session_id": session_id, "current": current, "proposed": proposed,
        "bump": bump, "last_tag": last_tag,
        "commits_since_tag": len(subjects),
        "reason": reason_lines[:5] if reason_lines else [f"{len(subjects)} patch-level commits"],
    }
    atomic_write_text(sess_dir / "version_bump.json", json.dumps(out, indent=2))
    _append_event(sess_dir, "release_version_proposed", {"bump": bump})
    return out


def generate_changelog(sessions_root: Path, *, session_id: str) -> dict:
    """Draft a CHANGELOG.md entry from commits since the last tag.

    Groups commits by Conventional Commits prefix:
      feat -> Added
      fix  -> Fixed
      refactor / perf -> Changed
      docs -> Documentation
      everything else -> Other
    """
    lc = ReleaseSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)
    project = Path(_meta(sess_dir)["project_path"])

    last_tag = _git(["describe", "--tags", "--abbrev=0"], cwd=project) or ""
    rng = f"{last_tag}..HEAD" if last_tag else "HEAD"
    log = _git(["log", "--pretty=format:%s", rng], cwd=project) or ""
    subjects = [s.strip() for s in log.splitlines() if s.strip()]

    groups: dict[str, list[str]] = {
        "Added": [], "Fixed": [], "Changed": [],
        "Documentation": [], "Other": [],
    }
    for s in subjects:
        if s.startswith("feat:") or s.startswith("feat!:"):
            groups["Added"].append(_strip_conv(s))
        elif s.startswith("fix:") or s.startswith("fix!:"):
            groups["Fixed"].append(_strip_conv(s))
        elif s.startswith("refactor:") or s.startswith("perf:") or s.startswith("refactor!:"):
            groups["Changed"].append(_strip_conv(s))
        elif s.startswith("docs:"):
            groups["Documentation"].append(_strip_conv(s))
        else:
            groups["Other"].append(s)

    today = now_iso()[:10]
    lines = [f"## [Unreleased] - {today}", ""]
    for heading, items in groups.items():
        if not items:
            continue
        lines.append(f"### {heading}")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    if not subjects:
        lines.append("_No commits since last tag._")
        lines.append("")

    md = "\n".join(lines).rstrip() + "\n"
    atomic_write_text(sess_dir / "changelog_entry.md", md)
    _append_event(sess_dir, "release_changelog_drafted", {"commits": len(subjects)})
    return {
        "session_id": session_id, "markdown": md,
        "commits_included": len(subjects),
        "path": str(sess_dir / "changelog_entry.md"),
    }


_REQUIRED_PYPROJECT = {
    "[project]name": re.compile(r"^name\s*=\s*['\"][^'\"]+['\"]", re.MULTILINE),
    "[project]version": re.compile(r"^version\s*=\s*['\"][^'\"]+['\"]", re.MULTILINE),
    "[project]description": re.compile(r"^description\s*=", re.MULTILINE),
    "[project]license": re.compile(r"^license\s*=", re.MULTILINE),
    "[project]authors": re.compile(r"^authors\s*=", re.MULTILINE),
    "[project]readme": re.compile(r"^readme\s*=", re.MULTILINE),
    "[project]requires-python": re.compile(r"^requires-python\s*=", re.MULTILINE),
}


def validate_pyproject(sessions_root: Path, *, session_id: str, path: str = "pyproject.toml") -> dict:
    """Check pyproject.toml for PyPI-required fields."""
    lc = ReleaseSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)
    project = Path(_meta(sess_dir)["project_path"])
    pp = project / path
    if not pp.is_file():
        return {"valid": False, "errors": [f"pyproject.toml not found at {pp}"], "path": str(pp)}

    text = pp.read_text(encoding="utf-8")
    errors: list[str] = []
    for label, pat in _REQUIRED_PYPROJECT.items():
        if not pat.search(text):
            errors.append(f"missing or unrecognized: {label}")
    if not (project / "LICENSE").exists() and not (project / "LICENSE.txt").exists():
        errors.append("LICENSE file not found at project root")

    out = {"valid": len(errors) == 0, "errors": errors, "path": str(pp)}
    atomic_write_text(sess_dir / "pyproject_validation.json", json.dumps(out, indent=2))
    _append_event(sess_dir, "release_pyproject_validated", {"valid": out["valid"]})
    return out


def build_dist(sessions_root: Path, *, session_id: str) -> dict:
    """Run `python -m build` and report the resulting artifacts."""
    lc = ReleaseSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)
    project = Path(_meta(sess_dir)["project_path"])

    rc, out, err = _run([_python_exe(), "-m", "build"], cwd=project)
    artifacts: list[str] = []
    dist = project / "dist"
    if dist.is_dir():
        artifacts = sorted(p.name for p in dist.iterdir())
    result = {
        "returncode": rc, "artifacts": artifacts,
        "stdout_tail": out[-1500:], "stderr_tail": err[-500:],
        "ok": rc == 0 and bool(artifacts),
    }
    atomic_write_text(sess_dir / "build.json", json.dumps(result, indent=2))
    _append_event(sess_dir, "release_build_done", {"ok": result["ok"], "n_artifacts": len(artifacts)})
    return result


def release_summary(sessions_root: Path, *, session_id: str) -> dict:
    """Aggregate version bump + pyproject validation + build status into
    a 'ready to twine upload' checklist."""
    lc = ReleaseSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    bump = _read_or_none(sess_dir / "version_bump.json")
    pp = _read_or_none(sess_dir / "pyproject_validation.json")
    build = _read_or_none(sess_dir / "build.json")

    checklist: list[dict] = [
        {"step": "Version bump proposed", "ok": bump is not None,
         "detail": (bump or {}).get("proposed", "(not run -- propose_version_bump)")},
        {"step": "pyproject.toml valid", "ok": (pp or {}).get("valid", False),
         "detail": (pp or {}).get("errors") or "ok" if pp else "(not run -- validate_pyproject)"},
        {"step": "dist built", "ok": (build or {}).get("ok", False),
         "detail": (build or {}).get("artifacts") or "(not run -- build_dist)"},
        {"step": "Changelog drafted", "ok": (sess_dir / "changelog_entry.md").exists(),
         "detail": "see changelog_entry.md" if (sess_dir / "changelog_entry.md").exists() else "(not run -- generate_changelog)"},
    ]
    ready = all(item["ok"] for item in checklist)
    summary = {
        "session_id": session_id, "ready": ready, "checklist": checklist,
        "next_action": (
            "Run `twine upload dist/*` (the suite NEVER auto-publishes)."
            if ready else "Address the failed checklist items above, then re-run release_summary."
        ),
    }
    atomic_write_text(sess_dir / "summary.json", json.dumps(summary, indent=2))
    _append_event(sess_dir, "release_summary", {"ready": ready})
    return summary


# ---------------------------------------------------------------- helpers


def _meta(sess_dir: Path) -> dict:
    return json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))


def _git(args: list[str], *, cwd: Path) -> str:
    rc, out, err = _run(["git"] + args, cwd=cwd, timeout=30)
    return out.strip() if rc == 0 else ""


def _run(cmd: list[str], *, cwd: Path, timeout: int = 600) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, check=False)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as exc:
        return 127, "", str(exc)


def _python_exe() -> str:
    """Return the python executable to use for `python -m build`."""
    import sys
    return sys.executable


_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _read_current_version(project: Path) -> str:
    pp = project / "pyproject.toml"
    if not pp.is_file():
        return ""
    m = _VERSION_RE.search(pp.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def _bump(version: str, kind: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return version
    major, minor, patch = (int(p) for p in parts)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _strip_conv(subject: str) -> str:
    return re.sub(r"^(feat|fix|refactor|chore|perf|docs)!?:\s*", "", subject)


def _read_or_none(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _append_event(sess_dir: Path, event_type: str, payload: dict) -> None:
    event = {"event_type": event_type, "payload": payload, "timestamp": now_iso()}
    append_jsonl_line(sess_dir / "events.jsonl", json.dumps(event))
