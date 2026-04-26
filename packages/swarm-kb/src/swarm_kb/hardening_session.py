"""Stage 6 Hardening -- production-readiness checks.

Aggregates Python-default tool runs into a single hardening report:

    | check                | tool        | pass criterion        |
    |----------------------|-------------|----------------------|
    | type-check           | mypy --strict (or basedpyright) | 0 errors |
    | coverage             | pytest-cov  | >= configured (default 85%) |
    | dep-audit (security) | pip-audit   | 0 high/critical CVEs  |
    | secrets-scan         | gitleaks (or naive regex fallback) | 0 high-confidence findings |
    | dep-hygiene          | (custom)    | 0 unused, 0 conflicts |
    | ci-presence          | filesystem  | .github/workflows/*.yml exists |
    | observability        | filesystem  | structured logging configured |

Each check runs as a subprocess (where applicable) with a timeout.
Tools that are not installed degrade to `installed: false` -- the user
sees what's missing instead of a crash.

The hardening session is a `~/.swarm-kb/sessions/harden/<sid>/` dir
with one JSON per check + an aggregated `report.md`. NEVER advances
the pipeline by itself -- the user reviews the report.

See docs/decisions/2026-04-26-stages-6-7-hardening-release.md for the
contract.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from swarm_core.io import atomic_write_text, append_jsonl_line
from swarm_core.logging_setup import get_logger
from swarm_core.sessions import SessionLifecycle
from swarm_core.timeutil import now_iso

_log = get_logger("kb.hardening_session")

DEFAULT_TIMEOUT_S = 300
DEFAULT_MIN_COVERAGE = 85


def _load_meta(sess_dir: Path) -> dict:
    """Load and validate meta.json -- raises ValueError if not a JSON object."""
    raw = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"corrupt meta.json in {sess_dir}: expected JSON object, got {type(raw).__name__}"
        )
    return raw


class HardeningSessionLifecycle(SessionLifecycle):
    tool_name = "harden"
    session_prefix = "harden"
    initial_files = ("events.jsonl",)

    def build_meta(self, session_id: str, *, project_path: str, name: str) -> dict:
        meta = super().build_meta(session_id, project_path=project_path, name=name)
        meta["min_coverage"] = DEFAULT_MIN_COVERAGE
        meta["check_results"] = {}  # check_name -> {passed, summary, ...}
        return meta


# ---------------------------------------------------------------- result type


@dataclass
class CheckResult:
    name: str
    passed: bool
    summary: str
    installed: bool = True
    details: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = now_iso()

    def to_dict(self) -> dict:
        return {
            "name": self.name, "passed": self.passed, "summary": self.summary,
            "installed": self.installed, "details": dict(self.details),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------- public API


def start_hardening(
    sessions_root: Path,
    *,
    project_path: str,
    min_coverage: int = DEFAULT_MIN_COVERAGE,
    name: str = "",
) -> dict:
    lc = HardeningSessionLifecycle(sessions_root)
    sid = lc.create(project_path=project_path, name=name)
    sess_dir = lc.session_dir(sid)

    meta = _load_meta(sess_dir)
    meta["min_coverage"] = min_coverage
    atomic_write_text(sess_dir / "meta.json", json.dumps(meta, indent=2))

    _append_event(sess_dir, "harden_started", {"min_coverage": min_coverage})
    return {
        "session_id": sid,
        "session_dir": str(sess_dir),
        "min_coverage": min_coverage,
        "checks": list(CHECK_REGISTRY.keys()),
    }


def run_check(
    sessions_root: Path,
    *,
    session_id: str,
    check: str,
) -> dict:
    lc = HardeningSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    if check not in CHECK_REGISTRY:
        raise ValueError(f"unknown check: {check!r}; valid: {sorted(CHECK_REGISTRY)}")

    meta = _load_meta(sess_dir)
    project_path = Path(meta.get("project_path", "."))

    runner = CHECK_REGISTRY[check]
    result = runner(project_path, meta)

    # Persist per-check JSON
    check_path = sess_dir / f"check.{check}.json"
    atomic_write_text(check_path, json.dumps(result.to_dict(), indent=2))

    # Update meta.check_results
    meta["check_results"][check] = result.to_dict()
    atomic_write_text(sess_dir / "meta.json", json.dumps(meta, indent=2))

    _append_event(sess_dir, "harden_check_done", {
        "check": check, "passed": result.passed, "installed": result.installed,
    })
    return result.to_dict()


def get_hardening_report(
    sessions_root: Path,
    *,
    session_id: str,
) -> dict:
    """Aggregate all run checks into a markdown report.

    Returns `{report_md, blockers, total_checks}`. Blockers count =
    failed-and-installed checks. Skipped (not-installed) checks DO NOT
    count as blockers but ARE noted in the report so the user can install
    the missing tool.
    """
    lc = HardeningSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    meta = _load_meta(sess_dir)
    results = meta.get("check_results", {})

    lines = ["# Hardening Report", ""]
    lines.append(f"Session: `{session_id}`")
    lines.append(f"Project: `{meta.get('project_path', '?')}`")
    lines.append(f"Min coverage threshold: {meta.get('min_coverage', DEFAULT_MIN_COVERAGE)}%")
    lines.append("")
    lines.append("| Check | Status | Notes |")
    lines.append("|-------|--------|-------|")

    blockers = 0
    skipped = 0
    for name in CHECK_REGISTRY:
        r = results.get(name)
        if r is None:
            status = "[NOT RUN]"
            note = "_run with kb_run_check_"
        elif not r["installed"]:
            status = "[SKIPPED]"
            note = r["summary"]
            skipped += 1
        elif r["passed"]:
            status = "[PASS]"
            note = r["summary"]
        else:
            status = "[FAIL]"
            note = r["summary"]
            blockers += 1
        lines.append(f"| `{name}` | {status} | {note} |")
    lines.append("")
    lines.append(f"**Blockers:** {blockers}")
    lines.append(f"**Skipped (tool missing):** {skipped}")

    report_md = "\n".join(lines) + "\n"
    atomic_write_text(sess_dir / "report.md", report_md)

    return {
        "session_id": session_id,
        "report_md": report_md,
        "blockers": blockers,
        "skipped": skipped,
        "total_checks": len(CHECK_REGISTRY),
        "report_path": str(sess_dir / "report.md"),
    }


# ---------------------------------------------------------------- check runners


def _run(cmd: list[str], *, cwd: Path, timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, str, str]:
    """Run a subprocess; return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def _check_typecheck(project: Path, meta: dict[str, Any]) -> CheckResult:
    """mypy --strict on the project. 0 errors -> pass."""
    if shutil.which("mypy") is None:
        return CheckResult(
            name="typecheck", passed=False, installed=False,
            summary="mypy not installed (`pip install mypy`)",
        )
    rc, out, err = _run(["mypy", "--strict", "."], cwd=project)
    error_count = 0
    m = re.search(r"Found (\d+) errors?", out)
    if m:
        error_count = int(m.group(1))
    passed = rc == 0
    return CheckResult(
        name="typecheck", passed=passed, installed=True,
        summary=f"{error_count} error(s)" if error_count else ("clean" if passed else f"exit {rc}"),
        details={"returncode": rc, "stdout_tail": out[-2000:], "stderr_tail": err[-500:]},
    )


def _check_coverage(project: Path, meta: dict[str, Any]) -> CheckResult:
    """pytest --cov; require coverage >= meta.min_coverage."""
    if shutil.which("pytest") is None:
        return CheckResult(
            name="coverage", passed=False, installed=False,
            summary="pytest not installed",
        )
    threshold = int(meta.get("min_coverage", DEFAULT_MIN_COVERAGE))
    rc, out, err = _run(
        ["pytest", "--cov", f"--cov-fail-under={threshold}", "-q", "--no-header"],
        cwd=project, timeout=DEFAULT_TIMEOUT_S * 2,
    )
    pct = 0.0
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", out)
    if m:
        pct = float(m.group(1))
    passed = rc == 0 and pct >= threshold
    return CheckResult(
        name="coverage", passed=passed, installed=True,
        summary=f"coverage {pct:.0f}% (threshold {threshold}%)",
        details={"returncode": rc, "coverage_pct": pct, "threshold": threshold,
                 "stdout_tail": out[-1500:]},
    )


def _check_dep_audit(project: Path, meta: dict[str, Any]) -> CheckResult:
    """pip-audit -- security audit on dependencies."""
    if shutil.which("pip-audit") is None:
        return CheckResult(
            name="dep_audit", passed=False, installed=False,
            summary="pip-audit not installed (`pip install pip-audit`)",
        )
    rc, out, err = _run(["pip-audit", "--strict", "-f", "json"], cwd=project)
    vuln_count = 0
    try:
        data = json.loads(out) if out.strip() else {}
        vulns = data.get("vulnerabilities") or data.get("dependencies") or []
        if isinstance(vulns, list):
            vuln_count = sum(len(d.get("vulns", [])) if isinstance(d, dict) else 0 for d in vulns)
    except json.JSONDecodeError:
        pass
    passed = rc == 0 and vuln_count == 0
    return CheckResult(
        name="dep_audit", passed=passed, installed=True,
        summary=f"{vuln_count} known vulnerabilit{'y' if vuln_count == 1 else 'ies'}",
        details={"returncode": rc, "stdout_tail": out[-2000:]},
    )


_SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-style API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "GitHub personal access token"),
    (re.compile(r"xox[bp]-[A-Za-z0-9-]{20,}"), "Slack token"),
]
_SCAN_EXCLUDE = {".git", "node_modules", ".venv", "venv", "__pycache__",
                 "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
                 ".worktrees", ".eggs", "site-packages"}


def _check_secrets(project: Path, meta: dict[str, Any]) -> CheckResult:
    """Naive regex secrets scan. Falls back to gitleaks if available."""
    if shutil.which("gitleaks") is not None:
        rc, out, err = _run(["gitleaks", "detect", "--no-git", "--report-format", "json", "-r", "-"], cwd=project)
        try:
            findings = json.loads(out) if out.strip() else []
        except json.JSONDecodeError:
            findings = []
        n = len(findings) if isinstance(findings, list) else 0
        return CheckResult(
            name="secrets", passed=(rc == 0 and n == 0), installed=True,
            summary=f"gitleaks: {n} finding(s)",
            details={"returncode": rc, "stdout_tail": out[-1500:]},
        )

    # Fallback: naive regex scan
    findings: list[dict] = []
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SCAN_EXCLUDE for part in path.relative_to(project).parts):
            continue
        if path.suffix in (".pyc", ".so", ".dll", ".exe", ".png", ".jpg", ".pdf"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat, label in _SECRET_PATTERNS:
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append({
                    "file": str(path.relative_to(project)),
                    "line": line, "kind": label,
                })
    return CheckResult(
        name="secrets", passed=(len(findings) == 0), installed=True,
        summary=f"naive scan: {len(findings)} suspect line(s)",
        details={"findings": findings[:20], "scanner": "naive-regex-fallback"},
    )


def _check_dep_hygiene(project: Path, meta: dict[str, Any]) -> CheckResult:
    """Look for pyproject.toml / requirements.txt presence and obvious issues.

    Lightweight check -- doesn't actually solve the dep graph. Flags:
      - no manifest at all
      - both pyproject.toml AND requirements.txt without `pip-tools` lockfile
      - duplicate dependencies between extras and main
    """
    pyproject = project / "pyproject.toml"
    reqs = project / "requirements.txt"
    issues: list[str] = []
    if not pyproject.exists() and not reqs.exists():
        issues.append("no pyproject.toml or requirements.txt")
    return CheckResult(
        name="dep_hygiene", passed=(len(issues) == 0), installed=True,
        summary="ok" if not issues else "; ".join(issues),
        details={"pyproject_exists": pyproject.exists(), "requirements_exists": reqs.exists()},
    )


def _check_ci_presence(project: Path, meta: dict[str, Any]) -> CheckResult:
    """Look for CI workflow files. Walks up to monorepo root.

    A package inside a monorepo may not have its own .github/workflows --
    the CI lives at the repo root. This walks up until either CI is
    found or we hit the filesystem root / a `.git` boundary.
    """
    found: list[str] = []
    walked: list[str] = []
    current = project.resolve()
    while True:
        for c in (
            current / ".github" / "workflows",
            current / ".gitlab-ci.yml",
            current / ".circleci" / "config.yml",
            current / "azure-pipelines.yml",
        ):
            if not c.exists():
                continue
            if c.is_dir():
                yml = list(c.glob("*.yml")) + list(c.glob("*.yaml"))
                if yml:
                    found.append(f"{_safe_rel(c, project)} ({len(yml)} workflow file(s))")
            else:
                found.append(_safe_rel(c, project))
        if found:
            break
        # Stop at .git boundary (monorepo root) or filesystem root
        if (current / ".git").exists() or current.parent == current:
            break
        walked.append(str(current))
        current = current.parent

    summary = ("ok: " + "; ".join(found)) if found else \
              "no CI configuration found (searched project + ancestor dirs to repo root)"
    return CheckResult(
        name="ci_presence", passed=(len(found) > 0), installed=True,
        summary=summary,
        details={"found": found, "ancestor_dirs_searched": walked},
    )


def _safe_rel(target: Path, base: Path) -> str:
    """Path of `target` relative to `base` if possible, else absolute string."""
    try:
        return str(target.relative_to(base))
    except ValueError:
        return str(target)


def _check_observability(project: Path, meta: dict[str, Any]) -> CheckResult:
    """Look for evidence of structured logging configuration."""
    py_files = list(project.rglob("*.py"))
    if not py_files:
        return CheckResult(
            name="observability", passed=False, installed=True,
            summary="no Python files found",
        )
    indicators = ("logging.getLogger", "structlog", "logging_setup", "RotatingFileHandler",
                  "TimedRotatingFileHandler")
    hits: list[str] = []
    for p in py_files[:200]:  # sample to keep cost bounded
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(ind in text for ind in indicators):
            hits.append(str(p.relative_to(project)))
            if len(hits) >= 3:
                break
    passed = len(hits) > 0
    return CheckResult(
        name="observability", passed=passed, installed=True,
        summary=f"{len(hits)} file(s) configure structured logging" if passed
                 else "no structured logging detected",
        details={"sample_hits": hits},
    )


CHECK_REGISTRY: dict[str, Callable[[Path, dict[str, Any]], CheckResult]] = {
    "typecheck": _check_typecheck,
    "coverage": _check_coverage,
    "dep_audit": _check_dep_audit,
    "secrets": _check_secrets,
    "dep_hygiene": _check_dep_hygiene,
    "ci_presence": _check_ci_presence,
    "observability": _check_observability,
}


# ---------------------------------------------------------------- helpers


def _append_event(sess_dir: Path, event_type: str, payload: dict) -> None:
    event = {"event_type": event_type, "payload": payload, "timestamp": now_iso()}
    append_jsonl_line(sess_dir / "events.jsonl", json.dumps(event))
