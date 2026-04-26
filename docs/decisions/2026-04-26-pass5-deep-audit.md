# 2026-04-26 -- Pass 5 deep audit findings + fixes

## Status

Sub-agent + manual deep audit. 26 findings reported by the explorer
agent, triaged to 5 actionable real bugs (rest were false positives,
test gaps, or non-runtime concerns). All 5 fixed in this commit.

## Real fixes

### F-1 (HIGH) -- Pipeline old-state compat broken

**Symptom:** Pipeline saved at the OLD 6-stage layout (before STAGE_ORDER
expanded with idea/plan/harden/release) loaded successfully via
`Pipeline.from_dict()` but raised `KeyError` on the next `advance()`
because `self.stages` was missing the new keys.

**Fix:** `Pipeline.__post_init__` now backfills any STAGE_ORDER stage
missing from `self.stages` with a PENDING `StageState`. Added a
test (`test_pipeline_loads_old_state_with_backfill`) loading a real
6-stage state dict and confirming `advance()` works.

### F-2 (HIGH) -- Lite-mode ID collisions at moderate volume

**Symptom:** `LiteFinding` and `LiteFixProposal` called
`generate_id("lf")` / `generate_id("lp")` with the default `length=2`
(16-bit suffix, 65k state). Birthday collision threshold ~256. A
test of 1000 generations produced 7 collisions.

**Fix:** Both classes now pass `length=4` (32-bit, ~4B state, birthday
threshold ~65k). Also added `schema_version: 1` to both serialized
dicts so future schema evolution can branch cleanly.

### F-3 (MEDIUM) -- Path traversal in kb_validate_pyproject

**Symptom:** `validate_pyproject(session_id, path="../../../etc/passwd")`
would attempt to read outside the project root. Tool didn't crash but
exposed filesystem probing via "found / not found" responses to MCP.

**Fix:** `validate_pyproject` now resolves `project / path` and rejects
the call if the resolved path is outside `project_path` (via
`Path.relative_to` check).

### F-4 (MEDIUM) -- Non-atomic writes in compat.py + quality_gate.py

**Symptom:** `compat.py` migration writes (`meta.json`, `debate.json`)
and `quality_gate.save_thresholds` used raw `path.write_text(...)`
instead of `swarm_core.io.atomic_write_text`. Concurrent readers could
see torn writes.

**Fix:** Both switched to `atomic_write_text`. compat.py imports it
lazily (only when migration runs) to avoid coupling at module load.

### F-5 (MEDIUM) -- keeper accepts unbounded file size

**Symptom:** `kb_check_claude_md(path)` exposed via MCP would call
`p.read_text(...)` on whatever path the caller passes. A 100 MB file
would OOM. Was an information-disclosure vector for an MCP-malicious
caller probing the host filesystem.

**Fix:** Keeper now `stat()`s before reading and rejects files larger
than 1 MiB with a CRITICAL finding. Bounds memory; signals "wrong
file passed" for the typo case.

### F-6 (LOW, test gap) -- No test for force=True / advance interplay

**Fix:** Added two tests in `test_stage_gates.py` documenting the
intended layering: PipelineManager is gate-agnostic; the MCP wrapper
is what enforces the gate. Tests exercise both the "blocked when gate
fails" and "advance succeeds when called directly" paths.

## False positives + non-issues from the agent (notes)

- **Race in `lite_dir()`:** flagged but innocuous. `mkdir(exist_ok=True)`
  is race-safe; `append_jsonl_line` uses `open(path, "a")` which creates
  on demand. Two concurrent calls produce two safe appends.
- **Race in concurrent `Pipeline.advance()`:** flagged but the
  `PipelineManager._lock` covers the full load-modify-save. Sequential
  serialization holds.
- **Git tag injection in release_session:** flagged but `_git` uses
  list-arg `subprocess.run` (no shell). Git tag names can't contain
  shell metachars. Worst case is a malformed `tag..HEAD` rev range
  which `git log` rejects.
- **`config.py` write_text encoding:** retracted by the agent in its
  own findings list.
- **Idempotent finalize_idea_design:** double-call overwrites cleanly.
  Agent flagged "no test" -- that's a test gap, not a bug.
- **Implicit Windows path issues:** `subprocess.run([list, ...])` is
  shell-injection-safe and handles path-with-spaces correctly.

## Final state after Pass 5 fixes

* 456 tests pass (was 453; +3 for backfill, force-blocked, force-advance).
* verify_e2e.py 47/47 still clean.
* check_imports OK.

## Lesson

Five review passes have surfaced bugs at every level (CLI wiring,
composition flow, script contradictions, gate enforcement, atomic
writes, ID collisions, compat). Each pass found different categories
because of different mental models. The lesson the keeper enforces in
its own dogfood: **no review is complete; the question is which classes
of bug you've checked for so far**. `verify_e2e.py` codifies the
checks that have been done; future passes target what's NOT covered
there.
