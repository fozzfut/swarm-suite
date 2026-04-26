# 2026-04-26 -- Real-work review findings + fixes

## Status

5 findings; all addressed in code + docs. Re-run of `verify_e2e.py`
clean (47/47), `pytest`: 453 (was 444, +9 stage-gate tests).

## Context

After unit tests + `verify_e2e.py` passed, ran another review pass with
the question: "would a new user trying to actually solve a problem with
this suite hit any sharp edges?" The 5 findings below are the gap
between "tests pass" and "ready for real users".

## Findings + fixes

### F-1 (CRITICAL) -- README pip-install path is broken

**Symptom:** README.md said `pip install swarm-core swarm-kb ...`. But
`swarm-core 0.1.0` is brand-new (never published). Bumped versions
(swarm-kb 0.3.0, review-swarm 0.4.0, fix-swarm-ai 0.3.0, doc-swarm-ai
0.2.0, spec-swarm-ai 0.2.0) are also unpublished. A new user following
README would get OLD versions from PyPI without any of the new tools
(Stage 0a/2/6/7, lite-mode, keeper, skill composition) -- silent
half-broken state.

**Fix:** README now says publishing is pending and recommends the
monorepo dev-install path (`scripts/install_all.py`) for the new
functionality. Old PyPI versions are listed as a still-functional
fallback.

### F-2 (MEDIUM) -- Pipeline gates were not enforced

**Symptom:** decision docs (e.g. stage-0a-idea-stage.md) specified that
`kb_advance_pipeline` from `idea -> arch` must require `idea_status ==
DESIGN_APPROVED`. In practice `Pipeline.advance()` had no content-state
check at all. Test:

    pipe = mgr.start("/proj")     # current_stage=idea
    mgr.advance(pipe.id)           # advanced! no idea_session ever existed.

User can blast through 10 stages without finalizing anything.

**Fix:** new module `swarm_kb.stage_gates` with `check_stage_gate(stage,
config) -> (ok, msg)`. Enforced for `idea`, `plan`, `harden`. The MCP
tool `kb_advance_pipeline` calls the gate before advancing; on failure
returns a structured error with hint + override path (`force=True`).
Other stages pass through (their own tools manage progression). 9 new
tests covering the gate behavior.

### F-3 (LOW) -- start_idea_session accepted empty prompt

**Symptom:** `start_idea_session(..., prompt="")` opened a session with
no anchor idea. Brainstorming has nothing to refine.

**Fix:** explicit `ValueError` with a hint to pass a one-paragraph
problem statement.

### F-4 (LOW) -- ci_presence check false-positive in monorepo packages

**Symptom:** Running `kb_run_check(check="ci_presence")` on
`packages/swarm-core/` reported "no CI configuration found", but the
swarm-suite repo has `.github/workflows/` at the repo root. The check
only looked at the project directory, not ancestors.

**Fix:** walks upward through parents until either CI is found or it
hits a `.git` boundary / filesystem root. Reports the ancestor dirs it
searched in `details`.

### F-5 (LOW) -- validate_pyproject LICENSE check false-positive in monorepo

**Symptom:** Same shape as F-4 -- LICENSE at repo root not detected
when validating a sub-package's pyproject.toml.

**Fix:** new `_has_license_in_ancestors(project)` walks up to the .git
boundary. Accepts `LICENSE`, `LICENSE.txt`, `LICENSE.md`.

## Things confirmed working

- Cross-tool data flow: `FindingWriter.post(...)` -> `FindingReader.read_all()` -> `search_all_findings(severity=...)` round-trips correctly.
- Composition prompt structure: 5 sections joined by clear `---` separators, each with an "Active skill: ..." announcement, no contradiction across sections, total ~25 KB for the heaviest expert (fix-swarm/security-fix).
- Logging: no f-string-in-log violations across the new modules (`swarm_core`, `swarm_kb` new code).
- Subprocess use: bounded -- only `release_session.py` (`python -m build`, `git`) and `hardening_session.py` (mypy / pytest-cov / pip-audit / gitleaks if installed). All have timeouts.
- Error paths: `ValueError` on bad inputs (rewind unknown pipeline, unknown check name, bad session id) -- all with informative messages, no raw stack traces.

## Pre-publish checklist (for when versions ship to PyPI)

When ready to publish the new versions:

1. `python -m build` for each of the 7 packages.
2. `twine check dist/*`
3. `twine upload` -- order matters because of inter-deps:
   - `swarm-core 0.1.0` first (foundation)
   - `swarm-kb 0.3.0` next (depends on swarm-core)
   - `review-swarm 0.4.0`, `fix-swarm-ai 0.3.0`, `doc-swarm-ai 0.2.0`, `spec-swarm-ai 0.2.0` -- all depend on swarm-core + swarm-kb
   - `arch-swarm-ai` -- bump from 0.2.4 to 0.3.0 first (it now depends on swarm_core.code_scan via the shim, even though pyproject didn't change). Add `swarm-core>=0.1.0` to its dependencies before publishing.
4. After publish, update README to drop the "publish pending" note.

## Lessons applied

- **karpathy.4 (Goal-Driven):** "tests pass" is a weak success criterion.
  The real goals are user-facing -- pip-install actually works, error
  messages actually help, gates actually block bad transitions. Each
  finding above is a place where unit tests passed but the user-facing
  goal would have failed.
- **systematic_debugging Iron Law:** the F-2 gate gap was knowable from
  reading the decision doc -- I just hadn't traced the `advance()` call
  path against what the doc promised. Verifying-against-the-spec is
  the missing Phase-1 step.
