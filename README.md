# ReviewSwarm

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-98%20passing-brightgreen.svg)]()
[![Version](https://img.shields.io/badge/version-0.1.1-orange.svg)](pyproject.toml)

Collaborative AI code review via MCP. Multiple specialized agents review your code simultaneously, coordinate through a shared whiteboard, and reach consensus on findings.

ReviewSwarm is **not** an LLM -- it's infrastructure. It provides 12 MCP tools that AI agents use to post findings, claim files, react to each other's work, and generate reports. You spawn the agents; ReviewSwarm coordinates them.

## Install

```bash
pip install review-swarm

# or from source
cd review-swarm
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize

```bash
review-swarm init
```

Creates `~/.review-swarm/config.yaml` with default settings.

### 2. Add to Claude Code

Add to your `~/.claude/settings.json` (or project `.mcp.json`):

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

Or with SSE transport (for multi-client like Cursor/Windsurf):

```json
{
  "mcpServers": {
    "review-swarm": {
      "url": "http://127.0.0.1:8787/sse"
    }
  }
}
```

Start the server first: `review-swarm serve --port 8787`

### 3. Run a Review

Tell your AI assistant:

> "Start a ReviewSwarm session for this project. Use the threading-safety, api-signatures, and consistency experts. Review all Python files in src/."

The agent will:
1. Call `start_session` with your project path
2. Call `suggest_experts` to see recommended experts
3. Call `claim_file` for each file it reviews
4. Call `post_finding` for each issue found (with evidence)
5. Call `get_findings` to see what other experts found
6. Call `react` to confirm/dispute other findings
7. Call `get_summary` for the final report

### 4. Multi-Agent Review (the real power)

Launch 3 parallel agents, each with a different expert role:

```
Agent A (threading-safety): "You are a Threading Safety Expert reviewing this project.
  Use the ReviewSwarm MCP tools. Session ID: sess-2026-03-21-001.
  Claim files before reviewing. Post findings with evidence.
  Check other experts' findings and react to them."

Agent B (api-signatures): same prompt, different role

Agent C (consistency): same prompt, different role
```

Each agent claims files, posts findings, and reacts to others' work. ReviewSwarm tracks consensus automatically:
- **2+ confirms** (no disputes) = finding is **confirmed**
- **1+ dispute** = finding is **disputed** (with reason)
- **duplicate** reactions link related findings

## CLI

```bash
review-swarm --version             # Show version
review-swarm init                  # Create default config
review-swarm serve --transport stdio  # Start MCP server (stdio)
review-swarm serve --port 8787     # Start MCP server (SSE)
review-swarm list-sessions         # List all sessions
review-swarm report <session-id>   # Generate report (markdown or --format json)
review-swarm purge --older-than 30 # Delete completed sessions older than 30 days
review-swarm purge --dry-run       # Preview what would be deleted
review-swarm prompt --list         # List available expert profiles
review-swarm prompt <expert-name>  # Print system prompt for an expert
```

## MCP Tools (12 total)

### Session Management
| Tool | Description |
|------|-------------|
| `start_session` | Start a review session for a project path |
| `end_session` | End session, release claims, get summary stats |
| `get_session` | Get current session state (finding counts, claims) |
| `list_sessions` | List all sessions |

### Expert Coordination
| Tool | Description |
|------|-------------|
| `suggest_experts` | Analyze project, recommend expert profiles |
| `claim_file` | Claim a file for review (prevents duplicate work) |
| `release_file` | Release a claimed file |
| `get_claims` | See which files are currently claimed |

### Findings
| Tool | Description |
|------|-------------|
| `post_finding` | Post a finding with evidence (actual + expected + source_ref) |
| `get_findings` | Query findings with filters (severity, file, status, etc.) |
| `react` | React to a finding: confirm, dispute, extend, or duplicate |
| `get_summary` | Generate markdown or JSON report |

### post_finding Parameters

Every finding requires evidence:

```
session_id:        "sess-2026-03-21-001"
expert_role:       "threading-safety"
file:              "src/server.py"
line_start:        42
line_end:          58
severity:          "critical" | "high" | "medium" | "low" | "info"
category:          "bug" | "omission" | "inconsistency" | "security" | "performance" | "style" | "design"
title:             "Race condition in cache update"
actual:            "self._cache[key] = value without lock"
expected:          "Cache writes should be protected by self._lock"
source_ref:        "src/server.py:45"
suggestion_action: "fix" | "investigate" | "document" | "ignore"
suggestion_detail: "Wrap cache write in 'with self._lock:' block"
confidence:        0.92
```

**Duplicate detection:** `post_finding` automatically returns `potential_duplicates` when another finding targets the same file + overlapping lines + similar title. The agent can then call `react` with `"duplicate"` to link them.

### react Parameters

```
session_id:          "sess-2026-03-21-001"
expert_role:         "api-signatures"
finding_id:          "f-a1b2c3"
reaction:            "confirm" | "dispute" | "extend" | "duplicate"
reason:              "Verified: no lock protection on lines 42-58"
related_finding_id:  "f-d4e5f6"   # for duplicate/extend only
```

## Built-in Expert Profiles (10)

| Profile | Focus Area | Key Checks |
|---------|-----------|------------|
| `threading-safety` | Concurrency | Race conditions, deadlocks, shared state, daemon cleanup |
| `api-signatures` | API Contracts | Signature mismatches, return types, deprecated APIs |
| `consistency` | Cross-References | Broken imports, stale re-exports, config-code drift |
| `error-handling` | Robustness | Swallowed errors, unchecked returns, broad catches |
| `resource-lifecycle` | Resource Leaks | Unclosed files, missing shutdown, use-after-close |
| `dead-code` | Code Hygiene | Unreachable code, unused exports, orphaned functions |
| `security-surface` | Security | Injection, hardcoded secrets, unsafe deserialization |
| `dependency-drift` | Dependencies | Unused/missing deps, manifest-lockfile drift |
| `project-context` | Documentation | CLAUDE.md/README accuracy, stale docs |
| `test-quality` | Test Quality | Weakened assertions, unrealistic mocks, missing coverage |

All profiles are **language-agnostic** -- they detect patterns across Python, JavaScript/TypeScript, Go, Rust, Java, C#, C/C++, Ruby, Elixir, Swift, and PHP.

### Custom Experts

Create YAML files in `~/.review-swarm/custom-experts/`:

```yaml
name: "My Custom Expert"
version: "1.0"
description: "Checks for project-specific patterns"
file_patterns: ["**/*.py", "**/*.js"]
exclude_patterns: ["tests/**"]
relevance_signals:
  imports: ["flask", "django"]
  patterns: ["request\\.", "cursor\\.execute"]
check_rules:
  - id: "my-check"
    description: "Description of what to check"
    severity_default: "high"
severity_guidance:
  critical: "When this happens..."
system_prompt: |
  You are a Custom Expert. Review code for...
```

### Using Expert Prompts

Extract any expert's system prompt for use with AI agents:

```bash
# List available experts
review-swarm prompt --list

# Get the full system prompt for threading-safety
review-swarm prompt threading-safety

# Pipe into clipboard (macOS)
review-swarm prompt security-surface | pbcopy
```

## Configuration

Optional. Create via `review-swarm init` or manually at `~/.review-swarm/config.yaml`:

```yaml
storage_dir: "~/.review-swarm"
max_sessions: 50
default_format: "markdown"

consensus:
  confirm_threshold: 2        # confirms needed without disputes
  auto_close_duplicates: true

experts:
  custom_dir: "~/.review-swarm/custom-experts"
  auto_suggest: true           # suggest experts on session start
```

Config is validated on load -- invalid values produce clear error messages.

## Data Storage

Sessions stored in `~/.review-swarm/sessions/`:

```
~/.review-swarm/sessions/
  sess-2026-03-21-001/
    meta.json          # Session metadata, status
    findings.jsonl     # Append-only findings log
    claims.json        # Current file claims
    reactions.jsonl    # Reaction log
```

## Development

```bash
pip install -e ".[dev]"
pytest                         # 98 tests, <1s
pytest -v --tb=short           # verbose output
mypy src/review_swarm/         # type checking
```

## How It Works

```
You (Claude Code / Cursor / Windsurf)
  |
  |  "Review this project with 3 experts"
  v
Spawn Agent A ──── MCP ──┐
Spawn Agent B ──── MCP ──┤
Spawn Agent C ──── MCP ──┤
                         v
              ReviewSwarm Server
              ┌─────────────────┐
              │  Shared State:  │
              │  - Findings     │  Agents read each other's work,
              │  - Claims       │  confirm or dispute findings,
              │  - Reactions    │  avoid reviewing same files.
              │  - Consensus    │
              └─────────────────┘
                         │
                         v
              Final Report (markdown/JSON)
              - Confirmed findings (2+ agrees)
              - Disputed findings (with reasons)
              - Per-file breakdown
              - Expert coverage map
```

## License

MIT
