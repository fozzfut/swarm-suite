<p align="center">
  <img src="https://img.shields.io/badge/ReviewSwarm-v0.2.0-blueviolet?style=for-the-badge" alt="Version" />
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
  <img src="https://img.shields.io/badge/tests-215%20passing-brightgreen.svg" alt="Tests" />
  <img src="https://img.shields.io/badge/experts-13-orange.svg" alt="Experts" />
  <img src="https://img.shields.io/badge/MCP_tools-24-blue.svg" alt="MCP Tools" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform" />
</p>

---

## One Command Review

```bash
review-swarm review . --scope src/ --task "security audit"
```

Or via MCP:

```
orchestrate_review(project_path=".", scope="src/", task="security audit")
```

ReviewSwarm creates a session, selects experts, assigns files, and returns a step-by-step plan. The LLM agent follows the plan — you get a complete multi-expert review report.

```
You: "Review src/ for security"
  │
  ▼
ReviewSwarm Orchestrator
  ├─ Creates session sess-2026-03-22-001
  ├─ Scans 47 source files in src/
  ├─ Selects: security-surface, error-handling, api-signatures
  ├─ Assigns files to experts
  └─ Returns 3-phase execution plan
       │
       ▼
  Phase 1: Review ─── each expert reviews files, posts findings
  Phase 2: Cross-check ─── experts confirm/dispute each other
  Phase 3: Report ─── aggregated report with consensus
```

**Task keywords** (EN/RU): security, performance, concurrency, quality, pre-release, bug, type, log, dependency, test, doc — the orchestrator auto-selects relevant experts.

---

## What is ReviewSwarm?

ReviewSwarm is **not** an LLM — it's **infrastructure**. It provides **24 MCP tools** that AI agents use to:

- **Post findings** with structured evidence (actual + expected + source_ref)
- **Claim files** for review (advisory locks with TTL)
- **React** to each other's work (confirm, dispute, extend, duplicate)
- **Message each other** — direct, broadcast, query/response (star topology)
- **Reach consensus** automatically (2+ confirms = confirmed)
- **Generate reports** in Markdown, JSON, or SARIF

**Key principle:** agents form a **REVIEW** — they produce a recommendation report, not code changes. Agents never modify project files.

---

## Install

```bash
pip install review-swarm
```

From source:

```bash
git clone https://github.com/fozzfut/review-swarm.git
cd review-swarm && pip install -e ".[dev]"
```

---

## IDE Setup

### Claude Code

Add to `~/.claude/settings.json` or project `.mcp.json`:

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

## MCP Tools (24)

### Orchestrator

| Tool | Description |
|------|-------------|
| `orchestrate_review` | One-command review. Provide scope + task, get a complete execution plan. |

### Session Management

| Tool | Description |
|------|-------------|
| `start_session` | Start a review session |
| `end_session` | End session, release claims, get summary |
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
| `post_finding` | Post finding with evidence. Rate-limited. Path-validated. |
| `post_findings_batch` | Post multiple findings in one call |
| `get_findings` | Query findings with filters + pagination |
| `find_duplicates` | Check for duplicates before posting |
| `react` | Confirm, dispute, extend, or mark duplicate |
| `post_comment` | Inline comment on a finding |
| `get_summary` | Generate Markdown/JSON report |

### Real-Time

| Tool | Description |
|------|-------------|
| `get_events` | Get events since timestamp (polling fallback) |

### Phase Barriers

| Tool | Description |
|------|-------------|
| `mark_phase_done` | Mark that an expert has completed a phase |
| `check_phase_ready` | Check if a phase can be started (all agents done with previous phase) |
| `get_phase_status` | Get full phase completion status for all agents |

### Agent Messaging (Star Topology)

| Tool | Description |
|------|-------------|
| `send_message` | Direct, broadcast, query, or response. Urgent + context. |
| `get_inbox` | Get messages with read tracking |
| `get_thread` | Get query + all responses |
| `broadcast` | Send to all agents |

Every tool response includes `_pending` — unread messages piggyback on every call so agents react immediately.

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

## Consensus

```
1+ duplicate  →  DUPLICATE
1+ dispute    →  DISPUTED
N+ confirm    →  CONFIRMED  (N = confirm_threshold, default 2)
otherwise     →  OPEN
```

---

## Agent Communication

Star topology — every agent reaches every other via the hub:

```
     threading-safety
            ↕
api-signs ↔ Hub ↔ consistency
            ↕
     security-surface
```

**Message types:** `direct`, `broadcast`, `query` (always urgent), `response`

**Piggyback `_pending`:** every tool response includes unread message count + preview. Agents react immediately — no polling loop, no race conditions.

**Context:** messages carry structured references to findings:

```json
{
  "content": "Is this lock pattern correct?",
  "urgent": true,
  "context": {
    "finding_id": "f-abc",
    "file": "src/cache.py",
    "line_start": 20,
    "severity": "critical"
  }
}
```

---

## Safety

| Feature | Details |
|---------|---------|
| Rate limiting | 60 findings/min, 120 messages/min per agent |
| Path validation | Rejects `../`, absolute paths, backslashes |
| Duplicate reactions | Same agent can't confirm/dispute same finding twice |
| Session auto-expiry | Active sessions expire after 24h |
| Atomic writes | JSONL uses temp file + `os.replace()` |
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

## Architecture

```
src/review_swarm/
├── orchestrator.py        # One-command review planning
├── server.py              # 24 MCP tools + resources + subscriptions
├── models.py              # Finding, Claim, Reaction, Event, Message
├── session_manager.py     # Session lifecycle, caching, auto-expiry
├── finding_store.py       # JSONL storage + in-memory index (atomic writes)
├── claim_registry.py      # Advisory file claims with TTL
├── reaction_engine.py     # Consensus engine + duplicate reaction guard
├── report_generator.py    # Markdown, JSON, SARIF reports
├── event_bus.py           # Real-time event pub/sub
├── message_bus.py         # Agent-to-agent messaging (star topology)
├── rate_limiter.py        # Per-agent sliding window rate limiter
├── expert_profiler.py     # Profile loading + auto-suggestion
├── logging_config.py      # Structured logging
├── config.py              # Config with validation
├── cli.py                 # Click CLI (review, tail, stats, diff, export...)
└── experts/               # 13 YAML expert profiles
```

---

## Data Storage

```
~/.review-swarm/sessions/sess-2026-03-22-001/
  ├── meta.json
  ├── findings.jsonl
  ├── claims.json
  ├── reactions.jsonl
  ├── events.jsonl
  └── messages.jsonl
```

---

## Development

```bash
pip install -e ".[dev]"
pytest                    # 215 tests, ~3s
mypy src/review_swarm/
```

CI: Python 3.10/3.11/3.12 on Ubuntu + Windows.

---

## License

[MIT](LICENSE) &copy; 2026 Ilya Sidorov
