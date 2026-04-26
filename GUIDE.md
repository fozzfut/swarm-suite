# Swarm Suite -- Complete Guide

## What is Swarm Suite

Swarm Suite is a set of **7 packages** (`swarm-core`, `swarm-kb`, `spec-swarm`, `arch-swarm`, `review-swarm`, `fix-swarm`, `doc-swarm`) -- 133+ MCP tools and 53 expert profiles -- for AI-assisted Python project development from **idea to production**.

AI agents (Claude Code, Cursor, Windsurf, Cline) call these tools to capture ideas, analyze hardware specifications, design architecture, plan implementation, review code, apply fixes, regenerate docs, harden for release, and ship -- with **SOLID + DRY** enforced at every stage.

No tool contains AI. They provide infrastructure: storage, coordination primitives, debate engine, quality gates, expert prompt registry, CLAUDE.md keeper. The AI agent does the thinking.

**Architecture:**
- `swarm-core` is the foundation (models, expert registry, session lifecycle, coordination primitives, MCP scaffolding, CLAUDE.md keeper).
- `swarm-kb` is the storage layer (findings, decisions, debates, pipelines).
- The five `*-swarm` tools depend only on `swarm-core` + `swarm-kb` -- never on each other. Layering enforced by `scripts/check_imports.py`.

For the layering rules see `docs/architecture/layering.md`. For the full pipeline spec see `docs/architecture/pipeline-stages.md`.

---

## Installation

```bash
# Full suite
pip install swarm-core swarm-kb review-swarm doc-swarm-ai fix-swarm-ai arch-swarm-ai spec-swarm-ai

# With PDF support (for datasheets and documentation)
pip install swarm-kb[pdf] spec-swarm-ai[pdf]

# Monorepo dev install (editable, dependency-ordered)
git clone https://github.com/fozzfut/swarm-suite
cd swarm-suite
python scripts/install_all.py
```

### MCP Server Setup

#### Claude Code

```bash
claude mcp add swarm-kb     -- swarm-kb serve --transport stdio
claude mcp add spec-swarm   -- spec-swarm serve --transport stdio
claude mcp add arch-swarm   -- arch-swarm serve --transport stdio
claude mcp add review-swarm -- review-swarm serve --transport stdio
claude mcp add fix-swarm    -- fix-swarm serve --transport stdio
claude mcp add doc-swarm    -- doc-swarm serve --transport stdio
```

#### Cursor / Windsurf / Cline (SSE)

Start each server on its own port, then add to MCP config:

```json
{
  "mcpServers": {
    "swarm-kb":     { "url": "http://localhost:8788/sse" },
    "spec-swarm":   { "url": "http://localhost:8769/sse" },
    "arch-swarm":   { "url": "http://localhost:8768/sse" },
    "review-swarm": { "url": "http://localhost:8765/sse" },
    "fix-swarm":    { "url": "http://localhost:8767/sse" },
    "doc-swarm":    { "url": "http://localhost:8766/sse" }
  }
}
```

---

## Getting Started

```
kb_guide("/path/to/project")
```

This detects your project type (Python/Node/Go/Rust/.NET/embedded) and shows the recommended workflow.

### Start a pipeline

```
# For embedded/hardware projects (starts with spec analysis)
kb_start_pipeline("/path/to/project", include_spec=True)

# For software projects (starts with architecture analysis)
kb_start_pipeline("/path/to/project")
```

---

## New tool surface (Stages 0a, 2, 6, 7 + lite-mode + keeper)

In addition to the original review/fix/doc/arch/spec tools, the swarm-kb
MCP server exposes:

**Stage 0a Idea (drives the brainstorming skill):**
- `kb_start_idea_session(project_path, prompt)`
- `kb_capture_idea_answer(session_id, question, answer)`
- `kb_record_idea_alternatives(session_id, alternatives, chosen_id)`
- `kb_finalize_idea_design(session_id, design_md)`

**Stage 2 Plan (drives the writing_plans skill):**
- `kb_start_plan_session(project_path, adr_ids)`
- `kb_emit_task(session_id, task_md)`
- `kb_finalize_plan(session_id, plan_md)` -- validates per the writing_plans contract

**Stage 6 Hardening (production-readiness checks, graceful degradation when tools missing):**
- `kb_start_hardening(project_path, min_coverage)`
- `kb_run_check(session_id, check)` -- one of: typecheck / coverage / dep_audit / secrets / dep_hygiene / ci_presence / observability
- `kb_get_hardening_report(session_id)` -- aggregated Markdown report with [PASS]/[FAIL]/[SKIPPED]

**Stage 7 Release (NEVER auto-publishes -- user runs twine):**
- `kb_start_release(project_path)`
- `kb_propose_version_bump(session_id)` -- Conventional Commits heuristic
- `kb_generate_changelog(session_id)`
- `kb_validate_pyproject(session_id, path)`
- `kb_build_dist(session_id)`
- `kb_release_summary(session_id)`

**Lite-mode (escape hatch from full-pipeline ceremony):**
- `kb_quick_review(file, line_start, line_end, severity, title, expert_role, ...)`
- `kb_quick_fix(file, line_start, line_end, old_text, new_text, rationale, expert_role, ...)`

**Pipeline backward navigation:**
- `kb_rewind_pipeline(pipeline_id, stage, reason)` -- when discoveries in stage N invalidate decisions from M < N

**CLAUDE.md keeper:**
- `kb_check_claude_md(path)` -- audits CLAUDE.md for size, accreted bug-fix recipes, missing required sections, missing pointers

**Prompt CLI (every tool, for setting up AI sub-agents):**
- `<tool> prompt <expert>` -- prints the composed system prompt (role + declared skills + universal skills) for an AI sub-agent. Available across all 5 tool CLIs (review-swarm / fix-swarm / doc-swarm / arch-swarm / spec-swarm).
- `<tool> prompt --list` -- lists available experts in that tool.
- `arch-swarm prompt --debate-roles <role>` -- prints prompts for the 5 hardcoded `AgentRole` debate participants (also gets universal skills appended).

See `docs/architecture/pipeline-stages.md` for the full lifecycle, `docs/architecture/skill-composition.md` for how skills compose into expert prompts, and `docs/decisions/` for individual stage contracts.

## Pipeline Stages

### Stage 0: Spec Analysis (SpecSwarm) — *embedded projects only*

**Purpose:** Extract and verify hardware specifications from datasheets before writing code.

**When to use:** New embedded project, hardware change, adding a new peripheral.

#### Step 1 — Ingest datasheets

```
spec_start_session("/project")
spec_ingest(session_id, "docs/STM32F407_datasheet.pdf", spec_type="datasheet", component_name="STM32F407VG")
spec_ingest(session_id, "docs/BME280_datasheet.pdf", spec_type="datasheet", component_name="BME280")
```

Automatically extracts: registers (addresses, fields, reset values), pins (AF, direction), protocols (SPI/I2C/CAN/UART/EtherCAT/Modbus/etc.), timing constraints, power specs, memory map.

#### Step 2 — Query extracted data

```
spec_get_registers(session_id, component="STM32F407VG", peripheral="CAN")
spec_get_pins(session_id)
spec_get_protocols(session_id)
spec_get_timing(session_id, critical_only=True)
spec_get_memory_map(session_id)
spec_check_conflicts(session_id)  → pin collisions, bus overload, power budget
```

#### Step 3 — Multi-agent verification

```
orchestrate_verification(session_id)
```

Returns a 4-phase plan for AI agents:
1. **Independent Verification** — each expert reads the ORIGINAL PDF (`kb_read_document`) and verifies extracted data field by field, with page number evidence
2. **Cross-Check** — experts review each other's verifications
3. **Resolve Disputes** — debates via `spec_start_debate` when experts disagree
4. **Generate Report** — `spec_generate_report` produces the verified Specification Report

#### Step 4 — Export for architecture

```
spec_export_for_arch(session_id)
```

Posts hardware constraints to swarm-kb as findings. ArchSwarm reads them automatically.

#### Step 5 — Advance pipeline

Review the report. Approve valid specs, correct any errors.

```
kb_advance_pipeline(pipeline_id)
```

**Tools (30):** `spec_start_session`, `spec_list_sessions`, `spec_ingest`, `spec_add_manual`, `spec_get_registers`, `spec_get_pins`, `spec_get_protocols`, `spec_get_timing`, `spec_get_memory_map`, `spec_get_constraints`, `spec_search`, `spec_check_conflicts`, `spec_suggest_experts`, `spec_export_for_arch`, `spec_generate_report`, `spec_get_summary`, `spec_start_verification`, `spec_claim_component`, `spec_release_component`, `spec_verify`, `spec_get_verifications`, `spec_verification_status`, `spec_send_message`, `spec_get_inbox`, `spec_broadcast`, `spec_mark_phase_done`, `spec_check_phase_ready`, `spec_start_debate`, `spec_verification_summary`, `orchestrate_verification`

**Experts (14):** mcu-peripherals, communication-protocols, industrial-protocols, power-management, sensor-interfaces, motor-control, memory-layout, timing-constraints, safety-requirements, requirements-analysis, api-specification, system-integration, standards-compliance, configuration-spec

---

### Stage 1: Architecture Analysis (ArchSwarm)

**Purpose:** Design software architecture informed by hardware constraints (if embedded) or project structure.

**When to use:** Before writing code, during major refactoring, when design decisions are needed.

#### Quick analysis (automated metrics)

```
arch_analyze("/project")
```

Scans AST and computes: coupling (afferent/efferent), complexity (cyclomatic), dependency graph, circular dependencies, class hierarchy. Posts findings to swarm-kb automatically.

#### Multi-agent debates (real AI analysis)

```
orchestrate_debate("/project", topic="Task scheduler design for 5ms CAN + 44ms sensor reading")
```

Returns a 4-phase plan for AI agents:
1. **Research & Propose** — each expert reads code + hw constraints, calls `kb_propose`
2. **Critique** — experts read all proposals, call `kb_critique` with concrete arguments
3. **Vote** — `kb_vote` backed by analysis of proposals + critiques
4. **Resolve** — `kb_resolve_debate` tallies votes, saves decision as ADR

Spec report (if available) is automatically included as context.

#### Advance pipeline

Review findings and decisions.

```
kb_advance_pipeline(pipeline_id)
```

**Tools (5):** `arch_analyze`, `arch_debate` (quick automated), `orchestrate_debate` (real multi-agent), `arch_list_sessions`, `arch_get_transcript`

**Experts (10):** simplicity, modularity, reuse, scalability, tradeoff-mediator, api-design, data-modeling, testing-strategy, dependency-architecture, observability

---

### Stage 2: Code Review (ReviewSwarm)

**Purpose:** Find bugs in code. Experts receive architectural decisions and hardware constraints as context.

**When to use:** After writing code, before release, during PR review.

#### Run review

```
orchestrate_review("/project", task="pre-release review")
```

Returns a 3-phase plan:
1. **Review** — 3-5 experts claim files, read code, post findings with evidence (actual, expected, source_ref)
2. **Cross-Check** — experts react to each other's findings (confirm/dispute/extend)
3. **Report** — `get_summary` generates the final report

Experts automatically receive:
- ADRs from ArchSwarm (`get_arch_context`)
- Hardware constraints from SpecSwarm
- `check_decision_compliance` flags findings that violate architectural decisions

#### Key tools during review

```
claim_file(session_id, "src/server.py", expert_role="security-surface")
post_finding(session_id, expert_role="security-surface",
    file="src/server.py", line_start=142, line_end=145,
    severity="high", category="security",
    title="SQL injection in query builder",
    actual="user input concatenated into query",
    expected="parameterized query",
    source_ref="src/server.py:142")
release_file(session_id, "src/server.py", expert_role="security-surface")

react(session_id, finding_id, expert_role="error-handling",
    reaction="confirm", comment="confirmed: no sanitization")
```

#### Advance pipeline

Review findings. Confirm valid ones, dismiss false positives.

```
kb_advance_pipeline(pipeline_id)
```

**Tools (28):** `start_session`, `end_session`, `get_session`, `list_sessions`, `suggest_experts`, `claim_file`, `release_file`, `get_claims`, `post_finding`, `post_findings_batch`, `get_findings`, `react`, `find_duplicates`, `post_comment`, `mark_fixed`, `bulk_update_status`, `get_events`, `mark_phase_done`, `check_phase_ready`, `get_phase_status`, `send_message`, `get_inbox`, `get_thread`, `broadcast`, `get_summary`, `check_decision_compliance`, `get_arch_context`, `orchestrate_review`

**Experts (13):** security-surface, performance, threading-safety, error-handling, api-signatures, consistency, dead-code, dependency-drift, logging-patterns, resource-lifecycle, test-quality, type-safety, project-context

---

### Stage 3: Fix (FixSwarm)

**Purpose:** Fix confirmed bugs with multi-agent consensus and regression protection.

**When to use:** After code review found issues.

#### Step 1 — Snapshot tests

```
snapshot_tests(session_id, base_dir="/project")
```

Saves test results as baseline for regression comparison.

#### Step 2 — Start fix session

```
start_session(review_session="sess-2026-03-24-001", project_path="/project")
```

Loads findings from ReviewSwarm + ArchSwarm. Loads architectural decisions.

#### Step 3 — Fix cycle (propose → review → consensus → apply)

```
suggest_experts(session_id)  → maps finding types to fix experts

# Expert claims a finding and proposes a fix
claim_finding(session_id, "f-abc123", "security-fix")
propose_fix(session_id, expert_role="security-fix",
    finding_id="f-abc123", file="src/server.py",
    line_start=142, line_end=145,
    old_text="query = f\"SELECT * FROM {table} WHERE id={user_id}\"",
    new_text="query = \"SELECT * FROM ? WHERE id=?\"\nparams = [table, user_id]",
    rationale="Parameterize query to prevent SQL injection")

# Other experts review the proposed fix
react(session_id, proposal_id, "refactoring",
    reaction_type="approve", comment="Fix is correct, doesn't break API")

# Apply only approved fixes
apply_approved(session_id, base_dir="/project")
```

Consensus rule: 2+ approvals → APPROVED, any rejection → REJECTED.

#### Step 4 — Quality gate check

```
kb_check_quality_gate(
    findings='[...]',       # from re-review of changed files
    fixes_applied=10,
    regressions=0,
    history='[...]'         # previous round metrics
)
→ {"recommendation": "continue"}  or  {"recommendation": "stop_clean"}
```

If `continue` → fix remaining issues, re-review, re-check gate.
If `stop_clean` → advance to verify.
If `stop_circuit_breaker` → STOP, investigate manually.

#### Step 5 — Advance pipeline

```
kb_advance_pipeline(pipeline_id)
```

**Tools (31):** `start_session`, `end_session`, `get_session`, `list_sessions`, `suggest_experts`, `claim_finding`, `release_finding`, `get_claims`, `propose_fix`, `get_proposals`, `get_proposal_reactions`, `react`, `apply_approved`, `apply_single`, `verify_fixes`, `run_tests`, `snapshot_tests`, `check_syntax`, `check_regression`, `send_message`, `get_inbox`, `broadcast`, `mark_phase_done`, `check_phase_ready`, `get_events`, `get_summary`, `load_decisions`, `load_debates`, `fix_plan` (legacy), `fix_apply` (legacy), `fix_verify` (legacy)

**Experts (8):** refactoring, security-fix, performance-fix, type-fix, error-handling-fix, test-fix, dependency-fix, compatibility-fix

---

### Stage 4: Regression Check

**Purpose:** Verify fixes didn't break anything.

```
check_regression(session_id, base_dir="/project")
→ {
    "syntax_ok": true,          ← all modified files parse
    "test_regression": false,    ← tests pass as before
    "new_findings": [],          ← no new issues in modified files
    "overall_ok": true
  }
```

Three checks:
1. **Syntax** — `ast.parse()` on all modified Python files
2. **Tests** — compare test results against snapshot (auto-detects pytest/npm/go/cargo/dotnet)
3. **Re-scan** — check modified files for regression indicators (empty functions, etc.)

If regression detected → go back to Stage 3, fix the regression.

```
kb_advance_pipeline(pipeline_id)
```

---

### Stage 5: Documentation (DocSwarm)

**Purpose:** Update documentation after code changes.

```
doc_scan("/project")      → code map (modules, classes, functions, docstrings)
doc_verify("/project")    → find stale docs that don't match code
doc_generate("/project")  → generate/update API documentation
```

```
kb_advance_pipeline(pipeline_id)  → Pipeline complete!
```

**Tools (4):** `doc_generate`, `doc_scan`, `doc_verify`, `doc_list_sessions`

**Experts (8):** api-reference, tutorial-writer, changelog-expert, migration-guide, architecture-docs, inline-docs, readme-quality, error-messages

---

## Quality Gate

The review-fix cycle repeats until quality thresholds are met.

### Default thresholds

| Parameter | Default | Meaning |
|-----------|---------|---------|
| max_critical | 0 | No critical code bugs allowed |
| max_high | 0 | No high code bugs allowed |
| max_medium | 3 | Up to 3 medium code bugs tolerated |
| max_weighted_score | 8 | CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1 |
| consecutive_clean_rounds | 2 | Two clean rounds confirm stability |
| max_iterations | 7 | Absolute limit on fix cycles |
| max_regression_rate | 10% | Max % of fixes that introduce new bugs |

### What counts as a "code bug"

Included: logic, type-safety, thread-safety, security, error-handling, data-integrity, regression, api-mismatch.

Excluded: architecture, style, documentation, dead-code, cosmetic, design.

### Circuit breaker (infinite loop protection)

| Condition | Action |
|-----------|--------|
| Max iterations reached (default: 7) | Stop, review manually |
| Weighted score increases N rounds in a row | Stop, fixes are making things worse |
| Same bug count for N rounds | Stop, cycle not making progress |
| Regression rate > 10% for 3+ rounds | Stop, fix process is unstable |

### Configure per project

```
kb_configure_quality_gate(
    max_critical=0,
    max_high=0,
    max_medium=5,            # relax for legacy projects
    max_weighted_score=12,
    max_iterations=10,       # more iterations for large projects
    consecutive_clean_rounds=2
)
```

---

## Debates

Any tool can start a debate when agents disagree. The debate engine lives in swarm-kb.

```
# Start
kb_start_debate(topic="Mutex vs task separation for shared SPI bus?",
                source_tool="fix", project_path="/project")

# AI agents participate
kb_propose(debate_id, author="Modularity Expert",
    title="Separate tasks per peripheral",
    description="Analysis: SPI1 shared between BME280 and MCP2515...")

kb_critique(debate_id, proposal_id, critic="Scalability Critic",
    verdict="modify", reasoning="Task separation adds context switch overhead...")

kb_vote(debate_id, agent="Trade-off Mediator",
    proposal_id=prop_id, support=True)

# Resolve
kb_resolve_debate(debate_id)
→ Winner selected, ADR saved to swarm-kb automatically
```

### Who starts debates

| Tool | When |
|------|------|
| SpecSwarm | Experts disagree on datasheet interpretation |
| ArchSwarm | Design question needs multi-perspective analysis |
| ReviewSwarm | Experts dispute a finding's severity or validity |
| FixSwarm | Two experts propose conflicting fixes |

---

## Shared Knowledge Base (swarm-kb)

All data flows through `~/.swarm-kb/`:

```
~/.swarm-kb/
├── sessions/
│   ├── spec/       spec analysis sessions
│   ├── arch/       architecture sessions + debate transcripts
│   ├── review/     code review sessions + findings
│   ├── fix/        fix sessions + proposals
│   └── doc/        documentation sessions
├── decisions/      architectural decisions (ADR)
├── debates/        debate engine state
│   └── active/     live debates
├── pipelines/      pipeline state (current stage per project)
├── code-maps/      AST analysis cache
├── xrefs.jsonl     cross-tool references (finding → fix → verification)
└── quality_gate.json   project quality thresholds
```

### Key tools

| Tool | Purpose |
|------|---------|
| `kb_guide` | Show workflow guide for current project |
| `kb_start_pipeline` | Start a new analysis pipeline |
| `kb_advance_pipeline` | User gate — advance to next stage |
| `kb_check_quality_gate` | Check if review-fix cycle can stop |
| `kb_post_finding` | Any tool posts findings |
| `kb_search_findings` | Search findings across all tools |
| `kb_post_decision` | Record an architectural decision |
| `kb_get_decisions` | Query active decisions |
| `kb_read_document` | Parse PDF/text into AI-readable format |
| `kb_start_debate` | Start a debate from any tool |
| `kb_resolve_debate` | Tally votes, save decision |

---

## Data Flow

```
SpecSwarm ──► kb_post_finding(hw constraints) ──────► ArchSwarm reads hw context
         ──► spec_generate_report ──────────────────► ArchSwarm debate context

ArchSwarm ──► kb_post_finding(coupling, complexity) ► FixSwarm reads arch issues
         ──► kb_post_decision(ADR) ─────────────────► ReviewSwarm checks compliance
         ──► kb_start_debate / kb_resolve ──────────► decisions available to all

ReviewSwarm → post_finding(code bugs) ──────────────► FixSwarm reads review findings
           → check_decision_compliance ◄────────────── reads ADRs from swarm-kb

FixSwarm ──► propose_fix → react → apply_approved ──► kb_post_xref(finding → fix)
         ──► check_regression ──────────────────────► verify no regressions

DocSwarm ──► doc_verify → doc_generate ─────────────► updated documentation
```

---

## Expert Profiles

All experts are YAML files. Language-agnostic. Customizable. No reference to any specific tool.

### SpecSwarm (14)

| Expert | Focus |
|--------|-------|
| mcu-peripherals | GPIO, clock tree, DMA, interrupts (STM32, ESP32, NXP, TI, Renesas) |
| communication-protocols | SPI, I2C, UART, USB — chip-level protocols |
| industrial-protocols | CAN, CANopen, EtherCAT, PROFINET, Modbus, OPC UA, EtherNet/IP, PROFIBUS, IO-Link, PROFIsafe, FSoE |
| power-management | Voltage rails, LDO/SMPS, sleep modes, current budget |
| sensor-interfaces | ADC, signal conditioning, calibration, filtering |
| motor-control | PWM, H-bridge, encoder, FOC, dead-time |
| memory-layout | Flash/RAM partitioning, linker scripts, bootloader, OTA |
| timing-constraints | Watchdog, RTOS deadlines, jitter, clock drift |
| safety-requirements | IEC 61508, MISRA, SIL, fail-safe, redundancy |
| requirements-analysis | SRS, PRD, user stories, acceptance criteria, traceability |
| api-specification | OpenAPI, gRPC, GraphQL, REST design, error contracts |
| system-integration | Data flow, protocol bridges, retry policies, circuit breaker |
| standards-compliance | ISO 9001, IEC 61508, ISO 26262, DO-178C, ISO 27001, GDPR |
| configuration-spec | Config files, env vars, feature flags, secret management |

### ArchSwarm (10)

| Expert | Focus |
|--------|-------|
| simplicity | YAGNI, over-engineering, unnecessary abstractions |
| modularity | SRP, coupling/cohesion, module boundaries, dependency direction |
| reuse | DRY, shared abstractions, library extraction |
| scalability | 10x growth, bottlenecks, concurrency models |
| tradeoff-mediator | Synthesis, pragmatic compromises, decision documentation |
| api-design | Naming, versioning, backward compatibility, error contracts |
| data-modeling | Normalization, schema evolution, migration strategy |
| testing-strategy | Test pyramid, mock boundaries, CI pipeline design |
| dependency-architecture | Layer violations, dependency cycles, package boundaries |
| observability | Structured logging, metrics, tracing, alerting |

### ReviewSwarm (13)

| Expert | Focus |
|--------|-------|
| security-surface | Injection, XSS, CSRF, auth, secrets exposure |
| performance | N+1 queries, quadratic algorithms, blocking I/O, memory leaks |
| threading-safety | Race conditions, deadlocks, unprotected shared state |
| error-handling | Swallowed errors, broad catches, missing propagation |
| api-signatures | Signature/usage mismatches, type contract violations |
| consistency | Cross-file contradictions, broken imports, naming mismatches |
| dead-code | Unreachable paths, unused exports, orphaned functions |
| dependency-drift | Unused deps, version conflicts, manifest inconsistencies |
| logging-patterns | Sensitive data in logs, missing correlation IDs, log injection |
| resource-lifecycle | Unclosed files/connections, missing cleanup, dangling refs |
| test-quality | Weakened assertions, unrealistic mocks, tests that validate bugs |
| type-safety | Unchecked null, unsafe casts, missing type guards |
| project-context | CLAUDE.md accuracy, architecture docs vs actual code |

### FixSwarm (8)

| Expert | Focus |
|--------|-------|
| refactoring | Extract method, rename, decompose conditional, simplify |
| security-fix | Parameterize queries, sanitize input, fix auth |
| performance-fix | Batch queries, add caching, fix N+1, replace linear search |
| type-fix | Add annotations, fix nullable, type narrowing |
| error-handling-fix | Add catches, narrow broad catches, add error context |
| test-fix | Fix assertions, improve isolation, fix flaky tests |
| dependency-fix | Update vulnerable deps, replace deprecated, resolve conflicts |
| compatibility-fix | Cross-version, cross-platform, feature detection |

### DocSwarm (8)

| Expert | Focus |
|--------|-------|
| api-reference | Public API documentation completeness |
| tutorial-writer | Tutorial quality, flow, working examples |
| changelog-expert | Release notes, semver compliance |
| migration-guide | Breaking changes, before/after, rollback steps |
| architecture-docs | ADRs, diagrams vs actual code |
| inline-docs | Misleading comments, stale TODOs, commented-out code |
| readme-quality | README completeness, install instructions, badges |
| error-messages | Helpful error messages, fix suggestions, error codes |

---

## Versions

| Package | Version | PyPI |
|---------|---------|------|
| swarm-kb | 0.2.9 | `pip install swarm-kb` |
| spec-swarm-ai | 0.1.6 | `pip install spec-swarm-ai` |
| arch-swarm-ai | 0.2.3 | `pip install arch-swarm-ai` |
| review-swarm | 0.3.10 | `pip install review-swarm` |
| fix-swarm-ai | 0.2.7 | `pip install fix-swarm-ai` |
| doc-swarm-ai | 0.1.8 | `pip install doc-swarm-ai` |

**Total: 133 MCP tools, 53 expert profiles, 6 packages.**

## License

MIT — Ilya Sidorov
