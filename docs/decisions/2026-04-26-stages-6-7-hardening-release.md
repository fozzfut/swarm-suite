# 2026-04-26 -- Stage 6 "Hardening" + Stage 7 "Release" implementation contracts

## Status

Specified. Not implemented. Both stages need substantial Python-tooling
opinions (which formatter? which type-checker? which dep-audit?) which
the user should make per project.

## Why

The current pipeline ends at Doc. A "production-grade" finish line is
implied by the Mission section in CLAUDE.md but not enforced. Without
Stages 6+7, the pipeline is "code is reviewed and documented" -- not
"code is shippable".

These two stages close the loop from idea to production.

## Stage 6: Hardening

**Purpose:** Verify the now-clean code is actually production-ready.

**Composite check** (each item is a separate sub-tool the user can run):

| Check | Tool | Threshold |
|-------|------|-----------|
| Type-check strict pass | mypy --strict | 0 errors |
| Test coverage | pytest-cov | >= configured (default 85%) |
| Security audit (deps) | pip-audit | 0 high/critical CVEs |
| Secrets scan | gitleaks or trufflehog | 0 high-confidence findings |
| Dependency hygiene | (custom check) | 0 unused deps; 0 conflicts |
| CI workflow exists | `.github/workflows/*.yml` present | true |
| Observability scaffolding | structured logging configured | true |

Each check returns a `KeeperFinding`-like dict. Aggregated as a
hardening report. Pipeline can't advance without operator override.

**Tool surface (new):**

```
kb_start_hardening(project_path: str) -> {sid: str}
kb_run_check(sid: str, check: str) -> {passed: bool, findings: [...]}
kb_get_hardening_report(sid: str) -> {report_md: str, blockers: int}
```

**Storage:** `~/.swarm-kb/sessions/hardening/<sid>/checks/<check>.json`,
plus `report.md`.

## Stage 7: Release

**Purpose:** Ship it. Bump version, write changelog, build, validate.

**Subtools:**

| Subtool | Action |
|---------|--------|
| `kb_propose_version_bump` | Read git log since last tag, propose patch/minor/major |
| `kb_generate_changelog` | Read session events since last release, draft `CHANGELOG.md` |
| `kb_validate_pyproject` | Check `pyproject.toml` for PyPI requirements (license, classifiers, ...) |
| `kb_build_dist` | Run `python -m build`; check `dist/` artifacts |
| `kb_release_summary` | Print "you are ready to `twine upload`" with checklist |

**Never auto-publishes.** The user runs `twine upload` themselves --
publishing to PyPI is a deliberate human action.

**Tool surface:**

```
kb_start_release(project_path: str) -> {sid: str}
kb_propose_version_bump(sid: str) -> {current: str, proposed: str, reason: str}
kb_generate_changelog(sid: str) -> {markdown: str}
kb_validate_pyproject(sid: str, path: str) -> {valid: bool, errors: [...]}
kb_build_dist(sid: str, project_path: str) -> {artifacts: [...]}
kb_release_summary(sid: str) -> {ready: bool, checklist: [...]}
```

**Storage:** `~/.swarm-kb/sessions/release/<sid>/` with each subtool
output as its own JSON.

## Why not implement now

These are genuinely opinionated -- what counts as "production-ready"
depends on the project. A minimum-viable Hardening stage requires
choosing tools (mypy-strict vs basedpyright? pip-audit vs safety?
gitleaks vs trufflehog?) and the user should pick those per project.

Implementation order suggested:
1. Land swarm-core extraction (other doc).
2. Land Stages 0a + 2 (other docs).
3. Then Hardening + Release once the pipeline is otherwise complete.

Until then the contract specified here is the API surface to build
against.
