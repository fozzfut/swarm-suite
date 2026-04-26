# Changelog

All notable changes to the Swarm Suite are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are tracked **per package** -- each `packages/<name>/pyproject.toml`
ships independently to PyPI; this file is the aggregate human-readable
history across the monorepo. The `[Unreleased]` section is the work
done since the last set of PyPI publishes; numbered sections mark the
versions that were actually pushed.

Suite follows semver per package:
- **patch** (`x.y.Z`): bug fixes, no schema change
- **minor** (`x.Y.0`): new tools / new fields with defaults
- **major** (`X.0.0`): schema break (must include a migration in
  `packages/swarm-kb/src/swarm_kb/compat.py`)

## [Unreleased]

Major thrust since the last published versions: porting 12 features from
[`kyegomez/swarms`](https://github.com/kyegomez/swarms) into the suite,
hardening it for enterprise use, and adding an AI-driven user-guidance
layer.

### Added

#### Self-direction / agent-loop primitives
- `swarm-core`: `CompletionTracker` (in-memory, hard caps for max
  subtasks / max-loops-per-subtask / max-consecutive-thinks),
  `CompletionRecord` / `SubtaskRecord` / `CompletionState` dataclasses,
  `CapExceededError` (subclass of `ValueError` so MCP boundary maps to
  `INVALID_PARAMS`).
- `swarm-kb`: `CompletionStore` -- per-session disk wrapper with
  cross-process safety (sibling `.lock` via `portalocker`); 5 new MCP
  tools `kb_subtask_done` / `kb_complete_task` / `kb_record_think` /
  `kb_record_action` / `kb_get_completion`.

#### Communication
- `swarm-core`: `Message.background` and `Message.intermediate_output`
  fields (`schema_version=2`, backward-compatible). Late-joining
  subscribers can resume from one event without rehydrating prior state
  from JSONL.
- `swarm-core`: `MessageBus.publish_structured(...)` +
  `StructuredPayload` TypedDict + `is_structured_payload()` helper.

#### Multi-agent debate framework
- `swarm-kb`: `debate_formats.py` registers 13 named protocols (`open`,
  `with_judge`, `trial`, `mediation`, `one_on_one`, `expert_panel`,
  `round_table`, `interview`, `peer_review`, `brainstorming`, `council`,
  `mentorship`, `negotiation`) over the same `DebateEngine` state
  model. Each format is a phase-spec (actors, phases, expected MCP
  calls, stop condition).
- `swarm-kb`: `Debate.format` field (`schema_version`-bumped, defaults
  to `open`); 2 new MCP tools `kb_list_debate_formats` and
  `kb_get_debate_format`.
- `swarm-kb`: `JudgingEngine` -- CouncilAsAJudge with 6 default
  dimensions (accuracy / helpfulness / harmlessness / coherence /
  conciseness / instruction_adherence) returning rationales (no
  numbers); 5 new MCP tools `kb_start_judging` / `kb_judge_dimension` /
  `kb_resolve_judging` / `kb_get_judging` / `kb_list_judgings`.

#### Quality gates
- `swarm-kb`: `VerificationStore` -- aggregates evidence
  (`test_diff` / `regression_scan` / `quality_gate` / `judging` /
  `manual_note`) into a single VerificationReport with structured
  verdict (`pass` / `fail` / `partial`); 5 new MCP tools.
- `swarm-kb`: `PgveStore` -- planner-generator-evaluator
  generate-verify-retry loop with auto-carried `previous_feedback`;
  5 new MCP tools.

#### Routing
- `swarm-core`: `swarm_core/textmatch.py` -- shared Jaccard /
  tokenisation utility (no embedding-model dependency).
- `swarm-core`: `TaskSimilarityStrategy` (in `experts/suggest.py`) +
  task-conditioned skill composition
  (`ExpertProfile.composed_system_prompt_for_task`) +
  `SkillRegistry.recommend_for_task` and `recommend_for_budget`.
- `swarm-core`: `Skill.cost` field (default 1.0) for cost-aware
  selection.
- `swarm-kb`: `kb_route_experts` MCP tool.

#### Pipeline DSL
- `swarm-kb`: `dsl.py` -- AgentRearrange-style flow parser
  (`->` sequence, `,` parallel, `H` human gate, `()` grouping). Bounded
  parser (`MAX_SOURCE_LEN=16KB`, `MAX_NODES=512`, `MAX_PARSE_DEPTH=64`)
  raises `FlowSyntaxError` instead of stack-overflowing on hostile
  input. Plus `FlowExecution` cursor + `FlowStore`.
- `swarm-kb`: 6 new MCP tools `kb_parse_flow` / `kb_start_flow` /
  `kb_get_next_steps` / `kb_mark_step_done` / `kb_get_flow` /
  `kb_list_flows`.

#### Navigator (AI-driven user guidance)
- `swarm-core`: `swarm_suite_navigator.md` skill (universal=true,
  auto-attaches alongside `solid_dry` and `karpathy_guidelines`).
  Instructs the AI client to call `kb_navigator_state` at session
  start + after every state-changing action, present 2-3 human-language
  options with WHY, ask ONE clarifying question if intent is unclear,
  execute MCP tool calls itself when the user picks (so the user never
  needs to memorise any of the 84 tool names), and confirm before
  destructive operations.
- `swarm-kb`: `navigator.py` + `kb_navigator_state` MCP tool --
  read-only single-call snapshot (active pipeline + open artifacts +
  recent decisions + current-stage info + 2-4 suggested_next_steps
  derived from rule-based templates).

### Changed

- `swarm-kb`: `STAGE_INFO['doc']` is now `optional: True`. Docs are
  typically only worth writing once for the final, ready-to-release
  project; running them on every fix iteration burns AI tokens for
  little payoff. Skip via `kb_skip_stage(pipeline_id, "doc")` during
  iteration.
- `swarm-kb`: 13 storage stores (Judging, Verification, Pgve, Flow,
  Completion) now use cross-process `portalocker` file lock around
  read-modify-write. Per-record sibling `.lock` keeps parallelism;
  different records mutate concurrently. Proven by 4 real-multiprocess
  tests spawning 10 OS processes per test.
- `swarm-kb`: every store gained input-bound validation
  (`MAX_TEXT_LEN=64KB`, `MAX_PAYLOAD_BYTES=1MB`, `MAX_DIMENSIONS=32`,
  `MAX_EVIDENCE_PER_REPORT=256`, etc.) raising `ValueError` ->
  `INVALID_PARAMS` at the MCP boundary.
- `swarm-kb`: every store gained `BoundedRecordCache` (LRU, default
  1000) so in-memory state stays bounded under long uptime; on-disk
  records persist independently.
- `swarm-kb`: every store's `from_dict` now warns on
  `schema_version > current` and normalises unknown `status` values
  to the default with a warning (per CLAUDE.md schema-versioning rule).
- `swarm-kb`: `dependencies` adds `portalocker>=2.7,<4`.
- Docs: README rewritten end-to-end -- new tagline naming both
  SOLID+DRY discipline (for user code) and Karpathy guidelines (for
  the AI itself), TOC after About, full Mermaid workflow diagrams
  (high-level + detailed-with-subgraphs + sequence diagrams for
  Review / Debate / Judging), all 53 experts listed with descriptions
  drawn from their YAML, all 7 skills documented (3 universal + 4
  opt-in), Hardening rationale + override guidance, "any Python project"
  positioning with embedded as opt-in.
- Docs: `CLAUDE.md` mission tagline drops "industrial code" ->
  "production".

### Fixed

- `pyproject.toml`: `[tool.pytest.ini_options]` now sets
  `addopts = "--import-mode=importlib"`. Without it, same-named test
  files across packages (`test_cli.py`, `test_models.py`) collided
  during root-level `pytest` collection and 4 packages errored out.
- Various Mermaid label-quoting fixes for GitHub's strict parser.

### Infrastructure

- New `.github/workflows/ci.yml`: matrix `{python: 3.10, 3.12} x
  {os: ubuntu, windows}` running `scripts/install_all.py +
  scripts/check_imports.py + pytest -v`. Plus advisory ruff lint job.
- Existing 117-test baseline grew to **709 tests** (+592 new across
  swarm-core + swarm-kb covering all the above primitives, including
  4 real-multiprocess cross-process safety tests + 7 in-memory
  end-to-end MCP client/server tests).

### Known limitations

- `#7` AgentRouter ships with Jaccard similarity (no embedding deps)
  per the original requirement to keep dependency surface small. A
  future opt-in `EmbeddingSimilarityStrategy` is foreseen but not
  implemented.
- `#12` SkillOrchestra cost-aware routing landed; the EMA-update of
  per-expert competence from `mark_fixed` outcomes is deferred (needs
  fix-swarm package edit, beyond swarm-kb-only scope).
- Cross-process safety is verified for two processes hammering the
  same record via `portalocker`. **Network-mounted KB roots**
  (NFS / SMB / Dropbox-style) remain documented as **unsupported**
  -- portalocker uses native `fcntl` / `LockFileEx` which are fragile
  across some network filesystems.

### ADRs (in `~/.swarm-kb/decisions/decisions.jsonl`)

- `adr-92c957e2` -- Self-direction completion tools (Bucket A)
- `adr-2b69593f` -- Structured Message payloads (item #6)
- `adr-9a76f0b5` -- Bucket B/C/D consolidated (judging + verification +
  pgve + cost-aware skills)
- `adr-9d18119b` -- AgentRouter via TF-IDF/Jaccard + Pipeline DSL
- `adr-20100a07` -- Enterprise hardening pass
- `adr-38773cbb` -- Cross-process file lock for storage engines

---

## Published versions on PyPI (frozen at the time of last release)

These were the versions at the start of the [Unreleased] thrust above.
The next publish run will bump per the changes accumulated under
[Unreleased].

| Package           | Last published version |
|-------------------|------------------------|
| `swarmsuite-core` | `0.1.0`                |
| `swarm-kb`        | `0.3.0`                |
| `arch-swarm-ai`   | `0.3.0`                |
| `review-swarm`    | `0.4.0`                |
| `fix-swarm-ai`    | `0.3.0`                |
| `doc-swarm-ai`    | `0.2.0`                |
| `spec-swarm-ai`   | `0.2.0`                |

For each package's per-version detail prior to this aggregate file,
see `packages/<name>/CHANGELOG.md` (where present) and the project's
git history.
