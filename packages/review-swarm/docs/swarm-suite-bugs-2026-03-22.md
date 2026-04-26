# Swarm Suite Bugs Found During QtLithoCAN Review
**Date:** 2026-03-22
**Context:** Full 12-expert ReviewSwarm + ArchSwarm review of QtLithoCAN project

---

## BUG 1: arch-swarm scans .venv (CRITICAL)

**File:** `arch-swarm/src/arch_swarm/code_scanner.py:171`

**Problem:** `scan_project()` uses `rglob("*.py")` without any directory filtering.
On a project with a 1GB `.venv`, it scanned **8835 modules / 3.5M lines** instead of ~150 project files / ~80k lines. The result was a 3MB JSON blob that was unusable.

**Code:**
```python
# code_scanner.py:171 -- NO skip-dir logic
py_files = sorted(scan_root.rglob("*.py"))
```

**Other swarm tools DO filter correctly:**

| Tool | File | Skip logic |
|------|------|-----------|
| **swarm-kb** | `code_map/scanner.py:21-26` | `_DEFAULT_SKIP_DIRS` set, checks every path part |
| **doc-swarm** | `code_analyzer.py:15-20` | Identical copy of swarm-kb logic |
| **review-swarm** | `expert_profiler.py:55-58` | Similar skip set (slightly smaller) |
| **arch-swarm** | `code_scanner.py` | **NOTHING** |

**swarm-kb reference implementation (correct):**
```python
_DEFAULT_SKIP_DIRS = {
    "node_modules", ".venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".tox",
    ".eggs", "site-packages",
}

# In scan loop:
for fp in sorted(scan_root.rglob("*")):
    rel_parts = fp.relative_to(root).parts
    if any(part in skip_dirs or part.endswith(".egg-info") for part in rel_parts):
        continue
```

**Fix:** Add the same `_SKIP_DIRS` filtering to `code_scanner.py` before the `for fp in py_files` loop.

---

## BUG 2: arch-swarm scope parameter broken

**Tool:** `arch_analyze(project_path, scope)`

**Problem:** When `scope="modules/ core/ services/"` is passed, it tries `root / scope` as a single path, which doesn't exist. Returns 0 modules.

```python
# code_scanner.py
scan_root = root / scope if scope else root  # "root/modules/ core/ services/" -- not a path!
if not scan_root.is_dir():
    return ArchAnalysis(root=str(root))  # Empty result
```

**Expected:** `scope` should accept multiple directories or glob patterns, not just a single subdirectory.

**Fix:** Parse scope as space-separated dirs, scan each, merge results.

---

## BUG 3: arch-swarm debates have no project context

**Tool:** `arch_debate(project_path, topic, scope)`

**Problem:** Debates produce generic LLM prompt templates instead of actual architectural analysis. The "proposals" are just the agent role descriptions, not real code-informed proposals. Example output:

```
### [Simplicity Critic] Simplicity Critic's proposal
[Prompt for LLM]
You are the Simplicity Critic. Your sole mission is to champion the simplest viable solution.
```

All 5 agents scored -3 (minimum). No real analysis happened.

**Root cause:** The debate agents don't actually read project code. They receive the (empty) scan result from `scan_project()` and generate placeholder responses.

**Fix:** Debate agents need to receive actual code context (scan results, file contents) to produce meaningful proposals.

---

## BUG 4: fix-swarm crashes on overlapping findings

**Tool:** `fix_verify(review_session, base_dir, threshold)`

**Problem:** When multiple experts report the same bug on the same lines (expected with 12 experts), `fix_verify` fails:

```
{"error": "Overlapping fixes in core/app_core.py: f-8463f8 (L491-499) and f-a1f153 (L491-499)"}
{"error": "Overlapping fixes in ui/widgets/exposure_plan_widget.py: f-10ee85 (L866-897) and f-4fee09 (L866-897)"}
```

This happens at every threshold (critical, high, medium).

**Expected:** Deduplicate findings on the same lines before verification. Multiple experts confirming the same bug is a feature, not an error.

**Fix:** Group findings by file+line range, treat overlapping findings as duplicates, verify once per unique location.

---

## BUG 5: review-swarm skip_dirs inconsistent with other tools

**File:** `review-swarm/src/review_swarm/expert_profiler.py:55-58`

**Problem:** review-swarm's skip set is smaller than swarm-kb/doc-swarm:

```python
# review-swarm (missing: .eggs, site-packages, .mypy_cache, .pytest_cache, .tox)
skip_dirs = {
    "node_modules", ".venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "vendor",  # "vendor" duplicated
}
```

vs swarm-kb:
```python
_DEFAULT_SKIP_DIRS = {
    "node_modules", ".venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".tox",
    ".eggs", "site-packages",
}
```

**Fix:** Unify to a shared constant across all tools, or at minimum copy swarm-kb's full set.

---

## Recommendation: Shared _SKIP_DIRS

All 4 scanning tools should use a single shared skip-dirs definition. Options:
1. Extract to a shared `swarm-common` package
2. Copy swarm-kb's `_DEFAULT_SKIP_DIRS` to each tool (quick fix)
3. Read `.gitignore` patterns (best but most work)
