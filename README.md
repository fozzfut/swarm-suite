<p align="center">
  <img src="https://img.shields.io/badge/ReviewSwarm-v0.3.5-blueviolet?style=for-the-badge" alt="Version" />
</p>

<h1 align="center">ReviewSwarm</h1>

<p align="center">
  <strong>Collaborative AI Code Review via MCP</strong><br>
  Multiple specialized AI agents review your code simultaneously,<br>
  coordinate through a shared whiteboard, and reach consensus on findings.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT" /></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python 3.10+" /></a>
  <img src="https://img.shields.io/badge/tests-227%20passing-brightgreen.svg" alt="Tests" />
  <img src="https://img.shields.io/badge/experts-13-orange.svg" alt="Experts" />
  <img src="https://img.shields.io/badge/MCP_tools-26-blue.svg" alt="MCP Tools" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform" />
</p>

---

## How It Works

ReviewSwarm is a **review-only** tool. It finds bugs, it does not fix them.

```
 You: "Review src/"
 ─────────────────►  ReviewSwarm Server
                     ┌────────────────────────┐
                     │  Phase 1: REVIEW        │
                     │  claim files             │
                     │  post findings           │
                     │  mark_phase_done         │
                     ├──────────────────────────┤
                     │  ═══════ BARRIER ═══════ │
                     ├──────────────────────────┤
                     │  Phase 2: CROSS-CHECK    │
                     │  get_findings             │
                     │  react (confirm/dispute)  │
                     │  mark_phase_done         │
                     ├──────────────────────────┤
                     │  ═══════ BARRIER ═══════ │
                     ├──────────────────────────┤
                     │  Phase 3: REPORT          │
                     │  end_session              │
                     │  auto-save reports        │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     report.md / report.json / report.sarif
                     (recommendation report — no code changes)
```

### Step by step

```bash
# 1. REVIEW: one command launches everything
review-swarm review . --scope src/ --task "security audit"

# Orchestrator: creates session, picks experts, assigns files, returns plan.
# Agents execute the plan:
#   Phase 1 — each expert reviews files, posts findings
#   ═══ BARRIER ═══ (all agents must finish before Phase 2)
#   Phase 2 — each expert reads others' findings, confirms/disputes
#   ═══ BARRIER ═══
#   Phase 3 — end_session auto-saves reports

# 2. REPORTS: auto-saved to session directory
ls ~/.review-swarm/sessions/sess-2026-03-22-001/
#   report.md      ← Markdown (executive summary, per-file, per-expert)
#   report.json    ← JSON (machine-readable)
#   report.sarif   ← SARIF 2.1.0 (GitHub Code Scanning)

# That's it. ReviewSwarm's job is done.
# The report is a spec — each finding has file, lines, evidence, and suggestion.
# What you do with it (manual fix, AI fix-agent, ignore) is up to you.
```

### Fix tracking (optional)

If you use a separate tool/agent to fix bugs from the report, you can track progress via ReviewSwarm:

```bash
# After fixing a bug, mark the finding as fixed:
mark_fixed(session_id, "f-a1b2c3", fix_ref="commit:abc1234")

# Or batch-update after fixing multiple bugs:
bulk_update_status(session_id, ["f-a1b2c3", "f-d4e5f6"], "fixed", reason="PR #42")
```

This is **status tracking**, not code modification. ReviewSwarm never changes your code.

### Key principles

- **Review agents are read-only** — they produce a recommendation report, never modify code
- **Phase barriers** — Phase 2 cannot start until all agents finish Phase 1
- **Consensus** — 2+ confirms = confirmed, 1+ dispute = disputed
- **Reports as specs** — each finding is a self-contained bug spec with file, lines, evidence, and suggestion
- **Fix tracking is optional** — `mark_fixed` / `bulk_update_status` track what was fixed, but fixing is external

---

## One Command Review

```bash
review-swarm review . --scope src/ --task "security audit"
```

Or via MCP:

```
orchestrate_review(project_path=".", scope="src/", task="security audit")
```

ReviewSwarm creates a session, selects experts, assigns files, and returns a 3-phase execution plan with barrier synchronization.

**Task keywords** (EN/RU): security, performance, concurrency, quality, pre-release, bug, type, log, dependency, test, doc — the orchestrator auto-selects relevant experts.

---

## What is ReviewSwarm?

ReviewSwarm is **not** an LLM and **not** a fixer — it's **review infrastructure**. It provides **26 MCP tools** that AI agents use to:

- **Post findings** with structured evidence (actual + expected + source_ref)
- **Claim files** for review (advisory locks with TTL)
- **React** to each other's work (confirm, dispute, extend, duplicate)
- **Message each other** — direct, broadcast, query/response (star topology)
- **Reach consensus** automatically (2+ confirms = confirmed)
- **Generate reports** in Markdown, JSON, or SARIF

ReviewSwarm produces a **recommendation report**. It never modifies your code. What you do with the report is up to you.

---

## Install

```bash
uv tool install review-swarm
```

Upgrade:

```bash
uv tool upgrade review-swarm
```

> Need uv? See [uv installation](https://docs.astral.sh/uv/getting-started/installation/).
> For the full swarm suite (ReviewSwarm + ArchSwarm + DocSwarm + FixSwarm + SpecSwarm + SwarmKB), see [INSTALL.md](INSTALL.md).

From source (development):

```bash
git clone https://github.com/fozzfut/review-swarm.git
cd review-swarm && pip install -e ".[dev]"
```

---

## IDE Setup

### Claude Code (recommended)

One command:

```bash
claude mcp add review-swarm -- review-swarm serve --transport stdio
```

Or add manually to `~/.claude/settings.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "review-swarm": {
      "command": "review-swarm",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

### Cursor / Windsurf / Cline (SSE)

Start server first: `review-swarm serve --port 8787`

```json
{
  "mcpServers": {
    "review-swarm": {
      "url": "http://127.0.0.1:8787/sse"
    }
  }
}
```

---

## CLI

```bash
# Orchestrator (one-command review)
review-swarm review . --scope src/ --task "security audit"
review-swarm review . --task "pre-release" --experts 5

# Server
review-swarm serve --transport stdio
review-swarm serve --port 8787

# Session management
review-swarm init
review-swarm list-sessions
review-swarm report <session-id>
review-swarm report <session-id> --format json

# Monitoring & analysis
review-swarm tail <session-id>                           # Live event stream
review-swarm stats                                       # Aggregate stats
review-swarm stats <session-id>                          # Session breakdown
review-swarm diff <session-a> <session-b>                # Compare reviews
review-swarm export <session-id> --format sarif -o out.sarif

# Expert profiles
review-swarm prompt --list
review-swarm prompt <expert-name>

# Maintenance
review-swarm purge --older-than 30
```

---

## MCP Tools (26)

### Orchestrator

| Tool | Description |
|------|-------------|
| `orchestrate_review` | One-command review. Provide scope + task, get a complete execution plan with phase barriers. |

### Session Management

| Tool | Description |
|------|-------------|
| `start_session` | Start a review session |
| `end_session` | End session, release claims, auto-save reports (md + json + sarif) |
| `get_session` | Get session state |
| `list_sessions` | List all sessions |

### Expert Coordination

| Tool | Description |
|------|-------------|
| `suggest_experts` | Recommend expert profiles for project |
| `claim_file` | Claim a file for review (30min TTL) |
| `release_file` | Release a claimed file |
| `get_claims` | See current claims |

### Findings

| Tool | Description |
|------|-------------|
| `post_finding` | Post finding with evidence. Rate-limited. Input-validated. |
| `post_findings_batch` | Post multiple findings in one call |
| `get_findings` | Query findings with filters + pagination (limit/offset) |
| `find_duplicates` | Check for duplicates before posting |
| `react` | Confirm, dispute, extend, or mark duplicate |
| `post_comment` | Inline comment on a finding |
| `get_summary` | Generate Markdown/JSON report |

### Fix Tracking

| Tool | Description |
|------|-------------|
| `mark_fixed` | Mark a finding as FIXED with optional commit/PR reference |
| `bulk_update_status` | Batch status update (fixed, wontfix, open, confirmed, disputed) |

### Phase Barriers (Two-Pass Sync)

| Tool | Description |
|------|-------------|
| `mark_phase_done` | Mark that an expert completed a phase |
| `check_phase_ready` | Check if all agents finished previous phase |
| `get_phase_status` | Full phase status for all agents |

### Real-Time Events

| Tool | Description |
|------|-------------|
| `get_events` | Get events since timestamp (polling fallback) |

### Agent Messaging (Star Topology)

| Tool | Description |
|------|-------------|
| `send_message` | Direct, broadcast, query, or response. Urgent + context. |
| `get_inbox` | Get messages with read tracking |
| `get_thread` | Get query + all responses |
| `broadcast` | Send to all agents |

Every tool response includes `_pending` — unread messages piggyback on every call so agents react immediately.

---

## Two-Pass Review with Phase Barriers

Agents can't start cross-checking until everyone finishes reviewing:

```
Phase 1: REVIEW
  Expert A reviews → mark_phase_done(sid, "threading-safety", 1)
  Expert B reviews → mark_phase_done(sid, "api-signatures", 1)
  Expert C reviews → mark_phase_done(sid, "consistency", 1)
                     ════════════ BARRIER ════════════
                     check_phase_ready(sid, 2) → ready: true

Phase 2: CROSS-CHECK
  Expert A reads findings, reacts → mark_phase_done(sid, "threading-safety", 2)
  Expert B reads findings, reacts → mark_phase_done(sid, "api-signatures", 2)
  Expert C reads findings, reacts → mark_phase_done(sid, "consistency", 2)
                     ════════════ BARRIER ════════════
                     check_phase_ready(sid, 3) → ready: true

Phase 3: REPORT
  end_session → auto-saves report.md + report.json + report.sarif
```

---

## Fix Tracking (Optional)

ReviewSwarm does not fix code. These tools are for **tracking** what was fixed externally:

```python
# After you (or your fix-agent) fix a bug, mark it in ReviewSwarm:
mark_fixed(session_id, "f-a1b2c3", fix_ref="commit:abc1234")

# Or batch-update:
bulk_update_status(session_id, ["f-a1b2c3", "f-d4e5f6"], "fixed",
                   reason="Fixed in PR #42")
```

Finding statuses: `open` → `confirmed` → `fixed` / `wontfix` / `disputed`

---

## 13 Expert Profiles

| Profile | Focus |
|---------|-------|
| `threading-safety` | Race conditions, deadlocks, async safety |
| `api-signatures` | Signature mismatches, type contracts |
| `consistency` | Broken imports, stale re-exports, config drift |
| `error-handling` | Swallowed errors, empty catches |
| `resource-lifecycle` | Unclosed files/connections, missing cleanup |
| `dead-code` | Unreachable code, unused exports |
| `security-surface` | Injection, secrets, unsafe deserialization |
| `dependency-drift` | Unused/missing deps, version conflicts |
| `project-context` | Documentation accuracy |
| `test-quality` | Weakened assertions, unrealistic mocks |
| `performance` | N+1 queries, O(n^2), memory leaks |
| `logging-patterns` | Sensitive data in logs, missing error logging |
| `type-safety` | Unchecked null, unsafe casts, any abuse |

All **language-agnostic**: Python, JS/TS, Go, Rust, Java, Kotlin, C#, C/C++, Ruby, Elixir, Swift, PHP.

---

## Consensus Algorithm

```
1+ duplicate  →  DUPLICATE
1+ dispute    →  DISPUTED
N+ confirm    →  CONFIRMED  (N = confirm_threshold, default 2)
otherwise     →  OPEN
```

---

## Agent Communication (Star Topology)

```
     threading-safety
            ↕
api-signs ↔ Hub ↔ consistency
            ↕
     security-surface
```

**Message types:** `direct`, `broadcast`, `query` (always urgent), `response`

**Piggyback `_pending`:** every tool response includes unread message count + preview. Agents react immediately — no polling loop, no race conditions.

---

## Safety

| Feature | Details |
|---------|---------|
| Rate limiting | 60 findings/min, 120 messages/min per agent |
| Path validation | Rejects `../`, absolute paths, backslashes |
| Input validation | Confidence 0-1, line numbers >= 0, line_end >= line_start |
| Duplicate reactions | Same agent can't confirm/dispute same finding twice |
| Session auto-expiry | Active sessions expire after 24h |
| Atomic writes | JSONL and JSON use temp file + `os.replace()` |
| Corruption recovery | Bad JSONL lines skipped with warning, not crash |
| Max findings | 10,000 per session |

---

## Configuration

`~/.review-swarm/config.yaml`:

```yaml
storage_dir: "~/.review-swarm"
max_sessions: 50
default_format: "markdown"
session_timeout_hours: 24

consensus:
  confirm_threshold: 2
  auto_close_duplicates: true

experts:
  custom_dir: "~/.review-swarm/custom-experts"
  auto_suggest: true

rate_limit:
  max_findings_per_minute: 60
  max_messages_per_minute: 120
```

---

## Data Storage

```
~/.review-swarm/sessions/sess-2026-03-22-001/
  ├── meta.json          # Session metadata + report paths
  ├── findings.jsonl     # Findings (one per line)
  ├── claims.json        # File claims
  ├── reactions.jsonl    # Reactions log
  ├── events.jsonl       # Real-time events
  ├── messages.jsonl     # Agent-to-agent messages
  ├── phases.json        # Phase barrier state
  ├── report.md          # Auto-saved Markdown report
  ├── report.json        # Auto-saved JSON report
  └── report.sarif       # Auto-saved SARIF report
```

---

## Architecture

```
src/review_swarm/
├── orchestrator.py        # One-command review planning
├── server.py              # 26 MCP tools + resources + subscriptions
├── models.py              # Finding, Claim, Reaction, Event, Message
├── session_manager.py     # Session lifecycle, caching, auto-expiry
├── finding_store.py       # JSONL storage + in-memory index (atomic writes)
├── claim_registry.py      # Advisory file claims with TTL (atomic writes)
├── reaction_engine.py     # Consensus engine + duplicate reaction guard
├── report_generator.py    # Markdown, JSON, SARIF reports
├── event_bus.py           # Real-time event pub/sub (thread-safe)
├── message_bus.py         # Agent messaging, star topology (thread-safe)
├── phase_barrier.py       # Two-pass sync barriers
├── rate_limiter.py        # Per-agent sliding window rate limiter
├── expert_profiler.py     # Profile loading + auto-suggestion
├── logging_config.py      # Structured logging
├── config.py              # Config with validation
├── cli.py                 # Click CLI (review, tail, stats, diff, export...)
└── experts/               # 13 YAML expert profiles
```

---

## Development

```bash
pip install -e ".[dev]"
pytest                    # 227 tests, ~3s
mypy src/review_swarm/
```

CI: Python 3.10/3.11/3.12 on Ubuntu + Windows.

---

## License

[MIT](LICENSE) &copy; 2026 Ilya Sidorov
