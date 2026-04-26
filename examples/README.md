# Swarm Suite -- end-to-end tutorial

This tutorial walks `examples/todo_api/` -- a deliberately-flawed Flask
Todo API -- through the Swarm Suite pipeline from architecture review
to release prep. The app ships with planted issues (SQL injection,
N+1 query, missing input validation, weak error handling, debug=True
in production code, missing tests) so the suite has real things to
find. **Don't deploy `todo_api/`.**

## Prerequisites

1. The suite installed and the MCP servers configured in your AI
   client. From the repo root:

   ```bash
   python scripts/install_all.py
   ```

   then add the servers to Claude Code (or Cursor / Windsurf / Cline)
   per the [README](../README.md#add-mcp-servers-claude-code).

2. The AI client running with the `swarm_suite_navigator` skill in
   scope (auto-attached to every expert via `composed_system_prompt`,
   so just talking to any swarm-* tool gives you it).

3. `cd examples/todo_api/` so the AI sees the example's working
   directory as the project root.

## How this tutorial works

You don't run a script. You **talk to your AI client** in plain
language. The AI reads `kb_navigator_state` to figure out where you
are in the pipeline, proposes 2-3 next steps, and executes the right
MCP tools when you agree. The numbered sections below are roughly
what one full pass looks like; **your AI will diverge as it learns
about your codebase, that's the point.**

Time to walk all stages: ~30-60 min interactive (mostly waiting for
multi-expert review and consensus to settle). The compute is on the
AI client side; the suite is just coordination + storage.

---

## Stage 1: Architecture (`arch-swarm`)

You: *"проанализируй архитектуру этого проекта"*

What the AI does:
1. Calls `kb_navigator_state` -- sees no pipeline yet -> offers to
   start one (default: arch).
2. After you say yes, calls `kb_start_pipeline(project_path=...)`.
3. Calls `arch_analyze` to scan structure.
4. For the Todo API, the report will note: only 2 modules so coupling
   is fine, no concerning dependency cycles, no concerning complexity
   per function. **Architecture is OK because the project is tiny.**
5. AI may offer: *"want to debate any specific design question (auth
   model, schema versioning, ...)? Or advance to review?"*
6. Pick `advance to review` for the demo.

Expected artifacts:
- `~/.swarm-kb/sessions/arch/<sid>/` with the analysis + any debate
  transcripts.
- ADRs in `~/.swarm-kb/decisions/decisions.jsonl` if you ran a debate.
- Pipeline advances to `review` stage.

---

## Stage 2: Code Review (`review-swarm`)

You: *"запусти ревью"*

What the AI does:
1. Calls `kb_navigator_state` -- sees pipeline at `review` -> offers
   to orchestrate.
2. Calls `kb_route_experts(task="...", experts_dir=...)` to pre-pick
   the most relevant of the 13 review experts. For Todo API, expect
   it to pick at least: `security-surface`, `error-handling`,
   `performance`, `test-quality`.
3. Calls `orchestrate_review`. Phase 1 (parallel claim/post/release)
   runs each picked expert against the codebase.
4. Phase 2 cross-check: experts react to each other's findings (e.g.
   `performance` confirms `security-surface`'s SQLi finding because
   it's also slow due to no index).
5. AI surfaces a summary: *"4 confirmed findings, 1 disputed. The
   high-severity ones are: SQLi in db.add_todo, debug=True in
   app.run, missing pagination, swallowed sqlite3.Error in
   delete_todo. Want me to triage?"*

Expected findings (typical):
- **HIGH** `security-surface`: SQL injection in `db.add_todo` (string
  concatenation instead of parameterised query)
- **HIGH** `security-surface`: `debug=True` in production
  `app.run(debug=True)`
- **MEDIUM** `performance`: N+1 query in
  `list_todos_with_owner_name`
- **MEDIUM** `error-handling`: bare `except sqlite3.Error: pass` in
  `delete_todo`
- **MEDIUM** `test-quality`: no test for `add_todo`, `delete_todo`,
  no SQLi regression test
- **LOW** various missing docstrings, no input validation in POST

You then triage: *"подтверди security findings, dismiss доку для
example app"* -- AI marks each one accordingly via `mark_fixed` /
`bulk_update_status`.

---

## Stage 3: Fix (`fix-swarm`)

You: *"пофиксь подтверждённые"*

What the AI does:
1. Calls `kb_navigator_state` -- sees pipeline at `fix`, 4 confirmed
   findings.
2. Offers options: fix all in batch, fix highest-severity first, or
   drive a PGVE retry-with-feedback loop on the SQLi finding (most
   likely to need iteration).
3. After you pick "fix all": calls `snapshot_tests` (baseline),
   `start_session` linked to the review session, then per finding
   propose -> consensus -> apply.
4. For the SQLi finding the AI may open a PGVE session
   (`kb_start_pgve(task_spec="parameterise db.add_todo")`):
   - Candidate v1: parameterised INSERT but loses the user lookup.
   - Evaluator says *revise: missing owner resolution.*
   - Candidate v2: parameterises both INSERT and SELECT.
   - Evaluator says *accepted.*
5. After `apply_approved`, calls `kb_check_quality_gate`. Most likely
   verdict: `stop_clean`.

Expected file changes:
- `db.py` -- `add_todo` uses parameterised SQL.
- `app.py` -- `app.run(debug=False)` (or removed entirely).
- `app.py` -- `delete_todo` returns 4xx on error instead of 204.
- `app.py` -- `todos_create` returns 400 on missing `title` field.
- `db.py` -- `list_todos_with_owner_name` uses a JOIN.

---

## Stage 4: Verify (`fix-swarm`)

You: *"проверь что не сломали"*

What the AI does:
1. Calls `check_regression`: runs the test suite (was 2/2 passing,
   should be 2/2 still); rescans for new findings.
2. Optionally builds a `VerificationReport` aggregating: test_diff
   (counts unchanged), regression_scan (clean), quality_gate (clean
   from previous stage). Finalises with `overall=pass`.
3. Offers: *"verify clean, доку запустим (optional, AI tokens) or
   straight to hardening?"*

Pick `straight to hardening` for the demo (Stage 6 is opt-in; doc on
this tiny example is overkill).

---

## Stage 5: Hardening (`swarm-kb`)

You: *"сделай hardening"*

What the AI does:
1. Calls `kb_start_hardening(project_path)`.
2. Runs `kb_run_check` for each: mypy strict, pytest-cov, pip-audit,
   gitleaks, dep-hygiene, ci-presence, observability.
3. For Todo API, expect failures at: pytest-cov (only 2 tests, < 85%),
   ci-presence (no `.github/workflows/`), observability (no logging
   setup). type-check and CVE-audit should be clean.
4. AI calls `kb_get_hardening_report` and shows the report. Suggests:
   *"add tests for delete + add_todo, add a tiny logging.basicConfig
   call, drop a basic .github/workflows/ci.yml -- want me to do
   each?"*
5. After fixes: re-run hardening, all checks green.

---

## Stage 6: Release prep (`swarm-kb`)

You: *"подготовь к релизу"*

What the AI does:
1. Calls `kb_start_release(project_path, package_path=...)`.
2. `kb_propose_version_bump` reads git log -> proposes `0.0.2`
   (patch).
3. `kb_generate_changelog` drafts a CHANGELOG entry citing the
   review/fix sessions.
4. `kb_validate_pyproject` -- our example pyproject is missing a few
   PyPI fields (license, author, urls). AI offers to add them.
5. `kb_build_dist` runs `python -m build`. Checks `dist/` for the
   .whl + .tar.gz.
6. `kb_release_summary` prints the "ready to twine upload" checklist.

You run `twine upload dist/*` yourself. Done.

---

## What you should observe end-to-end

- **You never typed an MCP tool name.** The navigator skill drove it
  all from your plain-language intent.
- **Every stage produced an inspectable artifact** in `~/.swarm-kb/`
  -- findings, debates (if any), decisions, judgings (if any),
  pgve sessions (if any), verification report, hardening report,
  release summary. Re-run is idempotent.
- **Cross-stage links** are intact: fix-session points back to the
  review-session it consumed; verification report cites the
  quality-gate result; release summary references the changelog
  entry.
- **The user gates were explicit.** Each stage waited for your `kb_advance_pipeline`.

## When things go wrong

- *"AI keeps offering me 5 things, not 2-3"* -- it's ignoring the
  `swarm_suite_navigator` skill. Make sure the suite is properly
  installed (the skill is universal, auto-attached). Check via
  `python scripts/verify_e2e.py --quick`.
- *"AI calls a tool that errors with INVALID_PARAMS"* -- usually
  means an input bound was hit (text > 64KB, payload > 1MB, etc.) --
  see `swarm_kb/_limits.py`.
- *"AI seems to forget what stage we're in"* -- it's not re-reading
  `kb_navigator_state`. Tell it to.
- *"want to skip a stage"* -- e.g. doc on a tiny example: tell the
  AI *"skip doc"* -- it will call `kb_skip_stage(pipeline_id, "doc")`.

## Re-running the tutorial

```bash
# Clean local KB for a fresh tutorial run:
rm -rf ~/.swarm-kb/sessions/* ~/.swarm-kb/pipelines/* \
       ~/.swarm-kb/decisions/* ~/.swarm-kb/debates/*
# Reset the example app:
cd examples/todo_api
git checkout .   # discard any AI-applied fixes
```

then start over from Stage 1.
