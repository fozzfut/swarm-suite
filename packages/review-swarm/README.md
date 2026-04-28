# review-swarm

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands — they never read this file. This README documents the package itself for contributors and standalone users.

Multi-agent **collaborative code review via MCP**. Thirteen specialised expert agents claim files in parallel, post findings with structured evidence, and reach consensus through a cross-check phase. Produces a recommendation report — **never modifies your code**.

This is **Stage 3** of the Swarm Suite pipeline: 13 experts claim files → post findings → cross-check phase reconciles → triaged report.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Experts](https://img.shields.io/badge/experts-13-orange.svg)]()
[![MCP tools](https://img.shields.io/badge/MCP_tools-28-blue.svg)]()

---

## How it works

```
Phase 1: REVIEW                Phase 2: CROSS-CHECK            Phase 3: REPORT
  claim_file()                   get_findings()                  end_session()
  post_finding() x N             react(confirm/dispute/extend)   auto-saves:
  release_file()                 mark_phase_done(2)                report.md
  mark_phase_done(1)             ════ BARRIER ════                 report.json
  ════ BARRIER ════                                                report.sarif
```

- **Review agents are read-only** — they produce a recommendation report, never modify code.
- **Phase barriers** — Phase 2 cannot start until all agents finish Phase 1.
- **Consensus** — 2+ confirms = `confirmed`; 1+ dispute = `disputed`; 1+ duplicate = `duplicate`.
- **Reports as specs** — each finding is a self-contained bug spec with file, lines, evidence, suggestion.

## Install

```bash
pip install review-swarm
```

For the full suite (recommended):

```bash
pip install swarmsuite-core swarm-kb arch-swarm-ai review-swarm fix-swarm-ai doc-swarm-ai
```

## Connect to your AI client

```bash
# Claude Code (built and tested)
claude mcp add review-swarm -- review-swarm serve --transport stdio
```

For Cursor / Windsurf / Cline (untested but should work via MCP), see the main [README § Connect to your AI client](../../README.md#connect-to-your-ai-client).

## CLI (standalone usage)

```bash
# Orchestrator (one-command review)
review-swarm review . --scope src/ --task "security audit"
review-swarm review . --task "pre-release" --experts 5

# Server
review-swarm serve --transport stdio
review-swarm serve --port 8787

# Sessions
review-swarm list-sessions
review-swarm report <session-id>
review-swarm report <session-id> --format json|sarif

# Monitoring
review-swarm tail <session-id>             # live event stream
review-swarm stats [<session-id>]          # aggregate / per-session
review-swarm diff <session-a> <session-b>  # compare reviews
review-swarm export <session-id> --format sarif -o out.sarif

# Expert profiles
review-swarm prompt --list
review-swarm prompt <expert-name>

# Maintenance
review-swarm purge --older-than 30
```

Task keywords (EN/RU) auto-select relevant experts: security, performance, concurrency, quality, pre-release, bug, type, log, dependency, test, doc.

## MCP tools (28)

### Orchestrator

| Tool | Description |
|------|-------------|
| `orchestrate_review` | One-command review. Provide scope + task, get a complete execution plan with phase barriers. |

### Sessions

| Tool | Description |
|------|-------------|
| `start_session` | Start a review session |
| `end_session` | End session, release claims, auto-save reports |
| `get_session` / `list_sessions` | Session state / list all |

### Expert coordination

| Tool | Description |
|------|-------------|
| `suggest_experts` | Recommend expert profiles for project |
| `claim_file` / `release_file` / `get_claims` | Advisory file claims with 30-min TTL |

### Findings + reactions

| Tool | Description |
|------|-------------|
| `post_finding` / `post_findings_batch` | Post findings with evidence (rate-limited, validated) |
| `get_findings` | Query with filters + pagination |
| `find_duplicates` | Check before posting |
| `react` | Confirm, dispute, extend, mark duplicate |
| `post_comment` | Inline comment on a finding |
| `get_summary` | Generate Markdown/JSON report |
| `mark_fixed` / `bulk_update_status` | Track external fix application |

### Phase barriers

| Tool | Description |
|------|-------------|
| `mark_phase_done` | Mark expert done with a phase |
| `check_phase_ready` | Check if all agents finished previous phase |
| `get_phase_status` | Full phase status for all agents |

### Real-time + messaging

| Tool | Description |
|------|-------------|
| `get_events` | Events since timestamp (polling fallback) |
| `send_message` | Direct, broadcast, query, response — star topology |
| `get_inbox` / `get_thread` / `broadcast` | Messaging with read tracking |

Every tool response includes `_pending` — unread messages piggyback on every call so agents react immediately.

### Decision compliance

| Tool | Description |
|------|-------------|
| `get_arch_context` | Pull ADRs from arch-swarm into review context |
| `check_decision_compliance` | Flag findings that violate Stage 1 architectural decisions |

## Expert profiles (13)

| Slug | Specialisation |
|------|----------------|
| `security-surface` | Injection vectors, hardcoded secrets, unsafe deserialization, missing input validation. |
| `performance` | N+1 queries, quadratic algorithms, memory leaks, blocking I/O on hot paths. |
| `threading-safety` | Race conditions, deadlocks, concurrency bugs across threads / async. |
| `error-handling` | Swallowed errors, empty catches, missing error propagation. |
| `type-safety` | Unchecked null / None / nil, unsafe type casts, missing type guards. |
| `api-signatures` | Function signatures match usage; types match contracts. |
| `consistency` | Cross-file contradictions: broken imports, naming mismatches, config/code drift. |
| `dead-code` | Unreachable paths, unused exports, orphaned functions, dead feature flags. |
| `dependency-drift` | Unused deps, missing deps, version conflicts, manifest/lockfile drift. |
| `logging-patterns` | Missing logging at error boundaries, sensitive data in logs. |
| `resource-lifecycle` | Resource leaks: unclosed files / connections / handles, missing cleanup. |
| `test-quality` | Weakened tests, unrealistic mocks, swallowed failures, assertion anti-patterns. |
| `project-context` | Validates `CLAUDE.md` / `AGENTS.md` accuracy vs codebase. |

All profiles are language-agnostic (Python, JS/TS, Go, Rust, Java, Kotlin, C#, C/C++, Ruby, Elixir, Swift, PHP). Every expert auto-loads the universal **SOLID + DRY** and **karpathy-guidelines** skills.

## Storage layout

```
~/.swarm-kb/review/sessions/sess-YYYY-MM-DD-NNN/
  ├── meta.json          # Session metadata + report paths
  ├── findings.jsonl     # Findings (append-only)
  ├── claims.json        # File claims (atomic write)
  ├── reactions.jsonl    # Reactions log (append-only)
  ├── events.jsonl       # Real-time events (append-only)
  ├── messages.jsonl     # Agent-to-agent messages
  ├── phases.json        # Phase barrier state
  ├── report.md          # Auto-saved Markdown report
  ├── report.json        # Auto-saved JSON report
  └── report.sarif       # Auto-saved SARIF 2.1.0 report
```

## Configuration

`~/.swarm-kb/config.yaml` (suite-wide):

```yaml
review:
  max_sessions: 50
  default_format: markdown
  session_timeout_hours: 24
  consensus:
    confirm_threshold: 2
    auto_close_duplicates: true
  rate_limit:
    max_findings_per_minute: 60
    max_messages_per_minute: 120
```

## Safety

| Feature | Details |
|---------|---------|
| Rate limiting | 60 findings/min, 120 messages/min per agent |
| Path validation | Rejects `../`, absolute paths, backslashes |
| Input validation | Confidence 0–1, line numbers ≥ 0, line_end ≥ line_start |
| Duplicate reactions | Same agent can't confirm/dispute same finding twice |
| Atomic writes | JSONL append + JSON via temp file + `os.replace()` |
| Corruption recovery | Bad JSONL lines skipped with warning, not crash |
| Max findings | 10,000 per session |

## Cost

13 experts working in parallel = up to 13× the LLM calls of a single-agent review. Pre-selecting experts (`--experts 5` or AgentRouter pre-filter) cuts this. See the main [README § A note on cost](../../README.md#a-note-on-cost) before launching on a large codebase.

## Development

```bash
git clone https://github.com/fozzfut/swarm-suite
cd swarm-suite/packages/review-swarm
pip install -e ".[dev]"
pytest                    # 227 tests, ~3s
mypy src/review_swarm/
```

CI: Python 3.10 / 3.11 / 3.12 on Ubuntu + Windows.

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
