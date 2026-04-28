# fix-swarm

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands — they never read this file. This README documents the package itself for contributors and standalone users.

Multi-agent **code fixer with consensus + regression protection**. Reads findings posted by [review-swarm](../review-swarm/) (and any other tool) from the shared swarm-kb, proposes fixes, runs a consensus vote (2+ approvals required), applies the fix, and verifies the test suite still passes. Refuses fixes that move the code *away* from SOLID + DRY.

This is **Stage 4** of the Swarm Suite pipeline: snapshot tests → propose fix → consensus → apply → regression check → quality gate.

## Install

```bash
pip install fix-swarm-ai
```

## Connect to your AI client

```bash
# Claude Code (built and tested)
claude mcp add fix-swarm -- fix-swarm serve --transport stdio
```

For Cursor / Windsurf / Cline (untested but should work via MCP), see the main [README § Connect to your AI client](../../README.md#connect-to-your-ai-client).

## Typical flow

The slash command `/swarm-fix` drives all of this for you. Under the hood it expands to:

```
snapshot_tests(session_id)                  # baseline test results
start_session(review_session, project_path) # load findings + ADRs
fix_plan(session_id, finding_id)            # propose a fix
propose_fix(...)                            # other experts review
react(..., reaction="approve")              # consensus voting (2+ approvals)
apply_single(session_id, finding_id)        # write changes to disk
fix_verify(session_id)                      # re-run tests, compare to baseline
kb_check_quality_gate(...)                  # circuit-breaker check
```

For one-off fixes that don't need consensus ceremony, use `kb_quick_fix` (lite mode — single expert, no debate).

## Expert profiles (8)

| Slug | Specialisation |
|------|----------------|
| `refactoring` | Safe refactoring patterns: extract method, rename, inline, decompose. |
| `security-fix` | Injection, XSS, CSRF, auth bypass, secret exposure. |
| `performance-fix` | Batch queries, caching, fix N+1, replace quadratic algorithms. |
| `type-fix` | Adds and fixes type annotations, null checks, narrows types. |
| `error-handling-fix` | Adds missing catches, narrows broad ones, retry/backoff. |
| `test-fix` | Fixes broken/flaky tests, adds missing assertions, isolation. |
| `dependency-fix` | Updates vulnerable packages, replaces deprecated APIs. |
| `compatibility-fix` | Cross-version / cross-platform compatibility shims. |

Every expert auto-loads the universal **SOLID + DRY**, **karpathy-guidelines**, and (opt-in) **systematic-debugging** skills — fixes are required to identify the root cause before patching.

## Cost

Fix proposals + consensus voting + regression checks mean each finding involves multiple LLM calls. Apply fixes one at a time (`/swarm-fix <finding_id>`) on a tight budget. See the main [README § A note on cost](../../README.md#a-note-on-cost).

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
