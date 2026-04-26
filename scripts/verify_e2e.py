"""End-to-end smoke harness for the Swarm Suite.

Goes beyond `pytest` (which exercises unit functions) and beyond
`scripts/test_all.py` (which exercises each package's tests). This
script:

  1. Confirms every tool's CLI invokes cleanly (subprocess --help).
  2. Constructs the swarm-kb MCP server and enumerates registered tools.
  3. Runs every new pipeline stage (Idea / Plan / Hardening / Release)
     end-to-end against a temp project.
  4. Confirms the `<tool> prompt <expert>` CLI surfaces composed prompts
     for all 5 tools (subprocess, real stdout, real expert YAMLs).
  5. Smoke-tests pipeline rewind, lite-mode, and keeper.
  6. Reasserts idempotency of every migration / attachment script.
  7. Final pytest run + check_imports + keeper (the standard gates).

Each section prints OK/FAIL with detail. Exit code 0 = clean.

Run from the repo root:
    python scripts/verify_e2e.py [--quick]

`--quick` skips the heavy parts (full pytest, dist build).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = (
    "swarm-core", "swarm-kb",
    "spec-swarm", "arch-swarm", "review-swarm", "fix-swarm", "doc-swarm",
)


def _build_pythonpath() -> str:
    parts = [str(REPO_ROOT / "packages" / p / "src") for p in PACKAGES]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


_ENV = {**os.environ, "PYTHONPATH": _build_pythonpath()}


# --------------------------------------------------------------- reporting


class Section:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def ok(self, label: str) -> None:
        self.passed.append(label)
        print(f"  OK    {label}")

    def fail(self, label: str, detail: str) -> None:
        self.failed.append((label, detail))
        print(f"  FAIL  {label}")
        for line in detail.splitlines():
            print(f"        {line}")

    def banner(self) -> None:
        bar = "=" * 70
        print(f"\n{bar}\n  {self.name}\n{bar}")

    def report(self) -> int:
        print(f"  -> {len(self.passed)} OK, {len(self.failed)} FAIL")
        return 1 if self.failed else 0


def run(cmd: list[str], *, cwd: Path = REPO_ROOT, timeout: int = 60) -> tuple[int, str, str]:
    """Run a subprocess; return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, check=False, env=_ENV)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


# --------------------------------------------------------------- sections


def section_1_clis() -> Section:
    s = Section("Section 1: CLI imports + Click setup")
    s.banner()

    expected = {
        "swarm-kb":      "swarm_kb.cli",
        "review-swarm":  "review_swarm.cli",
        "fix-swarm":     "fix_swarm.cli",
        "doc-swarm":     "doc_swarm.cli",
        "arch-swarm":    "arch_swarm.cli",
        "spec-swarm":    "spec_swarm.cli",
    }
    for name, mod in expected.items():
        rc, out, err = run([sys.executable, "-m", mod, "--help"])
        if rc == 0 and ("Usage:" in out or "Commands:" in out):
            s.ok(f"{name} --help")
        else:
            s.fail(f"{name} --help", f"rc={rc} stderr={err[:200]} stdout={out[:200]}")

    return s


def section_2_mcp_tools() -> Section:
    s = Section("Section 2: MCP server wiring (54 tools)")
    s.banner()

    rc, out, err = run([sys.executable, "-c",
        "from swarm_kb.server import create_mcp_server; "
        "mcp = create_mcp_server(); "
        "tools = sorted(mcp._tool_manager._tools.keys()); "
        "import json; print(json.dumps(tools))"
    ])
    if rc != 0:
        s.fail("create_mcp_server()", f"rc={rc} stderr={err[:300]}")
        return s

    try:
        tools = json.loads(out.strip())
    except json.JSONDecodeError:
        s.fail("parse tool list", f"output={out[:200]}")
        return s

    s.ok(f"create_mcp_server() succeeds, {len(tools)} tools")
    for required in [
        "kb_status", "kb_post_finding", "kb_advance_pipeline",
        "kb_check_claude_md", "kb_quick_review", "kb_quick_fix",
        "kb_start_idea_session", "kb_capture_idea_answer",
        "kb_record_idea_alternatives", "kb_finalize_idea_design",
        "kb_start_plan_session", "kb_emit_task", "kb_finalize_plan",
        "kb_start_hardening", "kb_run_check", "kb_get_hardening_report",
        "kb_start_release", "kb_propose_version_bump",
        "kb_generate_changelog", "kb_validate_pyproject", "kb_build_dist",
        "kb_release_summary", "kb_rewind_pipeline",
    ]:
        if required in tools:
            s.ok(f"tool registered: {required}")
        else:
            s.fail(f"tool MISSING: {required}", "not in tools list")

    return s


def section_3_pipeline_stages() -> Section:
    s = Section("Section 3: Stage 0a Idea + Stage 2 Plan + Stage 6 Hardening + Stage 7 Release")
    s.banner()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # ----- Stage 0a Idea -----
        rc, out, err = run([sys.executable, "-c", f"""
from pathlib import Path
from swarm_kb.idea_session import (start_idea_session, capture_idea_answer,
                                   record_alternatives, finalize_idea_design,
                                   IdeaStatus)

root = Path(r'{tmp}/idea')
out = start_idea_session(root, project_path='/x', prompt='CSV-Parquet CLI')
sid = out['session_id']
assert out['status'] == IdeaStatus.GATHERING
capture_idea_answer(root, session_id=sid, question='streaming?', answer='batch')
record_alternatives(root, session_id=sid, alternatives=[
    {{'id': 'a', 'title': 'Stream'}}, {{'id': 'b', 'title': 'Batch'}}
], chosen_id='b')
finalize = finalize_idea_design(root, session_id=sid, design_md='# Design\\nDetails.')
assert finalize['status'] == IdeaStatus.DESIGN_APPROVED
assert (root / sid / 'meta.json').is_file()
assert (root / sid / 'design.md').is_file()
print('idea-OK', sid)
"""])
        if rc == 0 and "idea-OK" in out:
            s.ok("Stage 0a Idea full lifecycle")
        else:
            s.fail("Stage 0a Idea", f"rc={rc} stderr={err[-400:]}")

        # ----- Stage 2 Plan -----
        valid_plan = """# Demo Implementation Plan

**Goal:** demo

**Architecture:** demo

**Tech stack:** Python

**ADR refs:** adr-1

---

### Task 1: Token

**Files:**
- Create: `src/x.py`

**Step 1: Write the failing test**

```python
def test_x():
    assert x() == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def x(): return 1
```

**Step 4: Run test to verify it passes**

Run: `pytest`
Expected: PASS

**Step 5: Commit**

```bash
git commit -m "feat: add x"
```
"""
        rc, out, err = run([sys.executable, "-c", f"""
from pathlib import Path
from swarm_kb.plan_session import (start_plan_session, emit_task,
                                   finalize_plan, PlanStatus)

root = Path(r'{tmp}/plan')
out = start_plan_session(root, project_path='/x', adr_ids=['adr-1'])
sid = out['session_id']
emit_task(root, session_id=sid, task_md='### Task 1: foo\\nbody')
plan_md = '''{valid_plan}'''
final = finalize_plan(root, session_id=sid, plan_md=plan_md)
assert final['validated'], final['errors']
assert final['status'] == PlanStatus.VALIDATED
print('plan-OK', sid)
"""])
        if rc == 0 and "plan-OK" in out:
            s.ok("Stage 2 Plan full lifecycle (with writing_plans validation)")
        else:
            s.fail("Stage 2 Plan", f"rc={rc} stderr={err[-400:]}")

        # ----- Stage 6 Hardening (lightweight checks only) -----
        rc, out, err = run([sys.executable, "-c", f"""
from pathlib import Path
from swarm_kb.hardening_session import (start_hardening, run_check,
                                        get_hardening_report)

# Use the swarm-suite repo itself as the project under test
proj = Path(r'{REPO_ROOT}')
root = Path(r'{tmp}/harden')
out = start_hardening(root, project_path=str(proj))
sid = out['session_id']
# Run only the cheap, deterministic checks
for c in ('dep_hygiene', 'ci_presence', 'observability', 'secrets'):
    run_check(root, session_id=sid, check=c)
report = get_hardening_report(root, session_id=sid)
assert 'report_md' in report
assert (root / sid / 'report.md').is_file()
print('harden-OK blockers=', report['blockers'])
"""], timeout=120)
        if rc == 0 and "harden-OK" in out:
            s.ok(f"Stage 6 Hardening (4 cheap checks against swarm-suite) -> {out.strip().split()[-1]}")
        else:
            s.fail("Stage 6 Hardening", f"rc={rc} stderr={err[-400:]}")

        # ----- Stage 7 Release (no build, just validate + propose) -----
        rc, out, err = run([sys.executable, "-c", f"""
from pathlib import Path
from swarm_kb.release_session import (start_release, propose_version_bump,
                                      generate_changelog, validate_pyproject,
                                      release_summary)

# Validate against swarm-core (it has a complete pyproject + LICENSE)
proj = Path(r'{REPO_ROOT}/packages/swarm-core')
root = Path(r'{tmp}/release')
out = start_release(root, project_path=str(proj))
sid = out['session_id']
bump = propose_version_bump(root, session_id=sid)
assert 'proposed' in bump
chg = generate_changelog(root, session_id=sid)
assert 'markdown' in chg
val = validate_pyproject(root, session_id=sid)
assert 'valid' in val
summary = release_summary(root, session_id=sid)
assert 'ready' in summary  # may not be ready -- that's expected without build
print('release-OK ready=', summary['ready'])
"""], timeout=60)
        if rc == 0 and "release-OK" in out:
            s.ok(f"Stage 7 Release (propose+changelog+validate, no build) -> {out.strip().split()[-1]}")
        else:
            s.fail("Stage 7 Release", f"rc={rc} stderr={err[-400:]}")

    return s


def section_4_prompt_clis() -> Section:
    s = Section("Section 4: <tool> prompt <expert> via subprocess (real CLI)")
    s.banner()

    cases = [
        ("review-swarm", "review_swarm.cli",   "security-surface",   ["SOLID + DRY", "Karpathy", "Self Review"]),
        ("fix-swarm",    "fix_swarm.cli",      "security-fix",       ["SOLID + DRY", "Karpathy", "Self Review", "Iron Law"]),
        ("doc-swarm",    "doc_swarm.cli",      "api-reference",      ["SOLID + DRY", "Karpathy", "Self Review"]),
        ("arch-swarm",   "arch_swarm.cli",     "simplicity",         ["SOLID + DRY", "Karpathy", "Self Review"]),
        ("spec-swarm",   "spec_swarm.cli",     "mcu-peripherals",    ["SOLID + DRY", "Karpathy"]),
    ]
    for tool, mod, expert, must in cases:
        rc, out, err = run([sys.executable, "-m", mod, "prompt", expert])
        if rc != 0:
            s.fail(f"{tool} prompt {expert}", f"rc={rc} err={err[:200]}")
            continue
        missing = [m for m in must if m not in out]
        if missing:
            s.fail(f"{tool} prompt {expert}", f"missing markers: {missing}")
        else:
            s.ok(f"{tool} prompt {expert} ({len(out):,} chars, {len(must)} markers)")

    # arch-swarm debate roles
    rc, out, err = run([sys.executable, "-m", "arch_swarm.cli",
                        "prompt", "--debate-roles", "Simplicity Critic"])
    if rc == 0 and "SOLID + DRY" in out and "Karpathy" in out:
        s.ok(f"arch-swarm prompt --debate-roles 'Simplicity Critic' ({len(out):,} chars)")
    else:
        s.fail("arch-swarm --debate-roles", f"rc={rc} err={err[:200]}")

    return s


def section_5_lite_keeper_rewind() -> Section:
    s = Section("Section 5: Lite-mode + keeper + pipeline rewind")
    s.banner()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # Lite quick_review
        rc, out, err = run([sys.executable, "-c", f"""
from pathlib import Path
from swarm_kb.config import SuiteConfig
from swarm_kb.lite_tools import kb_quick_review, kb_quick_fix

cfg = SuiteConfig(storage_root=r'{tmp}')
r = kb_quick_review(file='src/x.py', line_start=1, line_end=2,
                   severity='high', title='demo', expert_role='security',
                   config=cfg)
assert r['id'].startswith('lf-')
f = kb_quick_fix(file='src/x.py', line_start=1, line_end=2,
                 old_text='a', new_text='b', rationale='because',
                 expert_role='sec', config=cfg)
assert f['id'].startswith('lp-')
# Verify on-disk persistence
day_dir = next((Path(r'{tmp}')/ 'lite').iterdir())
assert (day_dir / 'lite-findings.jsonl').is_file()
assert (day_dir / 'lite-proposals.jsonl').is_file()
print('lite-OK', r['id'], f['id'])
"""])
        if rc == 0 and "lite-OK" in out:
            s.ok("kb_quick_review + kb_quick_fix end-to-end with on-disk persistence")
        else:
            s.fail("lite-mode", f"rc={rc} err={err[-400:]}")

        # Pipeline rewind
        rc, out, err = run([sys.executable, "-c", f"""
from pathlib import Path
from swarm_kb.pipeline import PipelineManager

mgr = PipelineManager(Path(r'{tmp}/pipelines'))
p = mgr.start('/some/proj')
mgr.advance(p.id); mgr.advance(p.id); mgr.advance(p.id)  # idea -> spec -> arch -> plan
result = mgr.rewind(p.id, 'spec', reason='ADR was wrong')
assert result['status'] == 'rewound'
assert result['current_stage'] == 'spec'
print('rewind-OK')
"""])
        if rc == 0 and "rewind-OK" in out:
            s.ok("kb_rewind_pipeline forward -> rewound state propagates correctly")
        else:
            s.fail("rewind", f"rc={rc} err={err[-400:]}")

    # Keeper on real CLAUDE.md
    rc, out, err = run([sys.executable, "-c",
        "from swarm_core.keeper.server import kb_check_claude_md_summary; "
        "print(kb_check_claude_md_summary('CLAUDE.md'))"
    ])
    if rc == 0 and "no findings" in out:
        s.ok(f"keeper on real CLAUDE.md: {out.strip()}")
    else:
        s.fail("keeper", f"rc={rc} out={out[:200]} err={err[:200]}")

    return s


def section_6_idempotency() -> Section:
    s = Section("Section 6: Migration + injection scripts idempotency")
    s.banner()

    for script, expect in [
        ("inject_solid_dry.py",        "skipped=53"),
        ("migrate_solid_dry_to_skill.py", "already-clean=53"),
        ("attach_skills.py",           "already-set=53"),
    ]:
        rc, out, err = run([sys.executable, f"scripts/{script}", "--dry-run"])
        if rc == 0 and expect in out:
            s.ok(f"scripts/{script} --dry-run idempotent ({expect})")
        else:
            s.fail(f"scripts/{script}", f"expected '{expect}' in output\nout={out[:300]}")

    # check_imports
    rc, out, err = run([sys.executable, "scripts/check_imports.py"])
    if rc == 0 and "OK" in out:
        s.ok(f"scripts/check_imports.py: {out.strip()}")
    else:
        s.fail("check_imports", f"rc={rc} out={out[:200]}")

    return s


def section_7_pytest() -> Section:
    s = Section("Section 7: Final pytest sweep across all 6 packages")
    s.banner()

    rc, out, err = run([sys.executable, "scripts/test_all.py", "-q", "--tb=no"],
                       timeout=300)
    # Parse "N passed" lines
    counts = []
    for line in out.splitlines():
        if "passed" in line:
            counts.append(line.strip())
    total = sum(int(line.split()[0]) for line in counts if line.split()[0].isdigit())
    if rc == 0 and "All packages green" in out and total >= 400:
        s.ok(f"All packages green ({total} tests passed)")
    else:
        s.fail("test_all", f"rc={rc} total={total}\ntail={out[-500:]}")

    return s


# --------------------------------------------------------------- entrypoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="Skip the full pytest sweep (Section 7).")
    args = parser.parse_args()

    sections: list[Section] = []
    sections.append(section_1_clis())
    sections.append(section_2_mcp_tools())
    sections.append(section_3_pipeline_stages())
    sections.append(section_4_prompt_clis())
    sections.append(section_5_lite_keeper_rewind())
    sections.append(section_6_idempotency())
    if not args.quick:
        sections.append(section_7_pytest())

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    total_pass = sum(len(s.passed) for s in sections)
    total_fail = sum(len(s.failed) for s in sections)
    for s in sections:
        marker = "OK  " if not s.failed else "FAIL"
        print(f"  [{marker}] {s.name}: {len(s.passed)} ok, {len(s.failed)} fail")
        for label, _detail in s.failed:
            print(f"           - {label}")
    print(f"\n  Total: {total_pass} OK, {total_fail} FAIL")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
