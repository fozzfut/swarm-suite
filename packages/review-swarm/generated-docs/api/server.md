---
title: Server
type: api
status: draft
source_files:
- src/review_swarm/server.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/server.py
lines_of_code: 1102
classes:
- AppContext
functions:
- create_app_context
- tool_start_session
- tool_end_session
- tool_get_session
- tool_list_sessions
- tool_suggest_experts
- tool_claim_file
- tool_release_file
- tool_get_claims
- tool_post_finding
- tool_get_findings
- tool_react
- tool_get_summary
- tool_orchestrate_review
- tool_find_duplicates
- tool_mark_fixed
- tool_bulk_update_status
- tool_post_findings_batch
- tool_post_comment
- tool_get_events
- tool_send_message
- tool_mark_phase_done
- tool_check_phase_ready
- tool_get_phase_status
- tool_get_inbox
- tool_get_thread
- tool_broadcast
- create_mcp_server
---

# Server

MCP Server with 26 tool handlers, MCP Resources, subscriptions, event bus, and agent messaging.

**Source:** `src/review_swarm/server.py` | **Lines:** 1102

## Dependencies

- `collections.abc`
- `config`
- `contextlib`
- `dataclasses`
- `expert_profiler`
- `json`
- `logging_config`
- `mcp.server.fastmcp`
- `models`
- `orchestrator`
- `rate_limiter`
- `report_generator`
- `session_manager`
- `threading`
- `typing`

## Classes

### `class AppContext`

**Lines:** 23-32

## Functions

### `def create_app_context(config: Config | None=None, project_path_override: str | None=None) -> AppContext`

**Lines:** 35-67

### `def tool_start_session(ctx: AppContext, project_path: str, name: str | None=None) -> dict`

**Lines:** 74-76

### `def tool_end_session(ctx: AppContext, session_id: str) -> dict`

**Lines:** 79-84

### `def tool_get_session(ctx: AppContext, session_id: str) -> dict`

**Lines:** 87-88

### `def tool_list_sessions(ctx: AppContext) -> list[dict]`

**Lines:** 91-92

### `def tool_suggest_experts(ctx: AppContext, session_id: str) -> list[dict]`

**Lines:** 95-97

### `def tool_claim_file(ctx: AppContext, session_id: str, file: str, expert_role: str, agent_id: str='unknown') -> dict`

**Lines:** 100-107

### `def tool_release_file(ctx: AppContext, session_id: str, file: str, expert_role: str) -> dict`

**Lines:** 110-116

### `def tool_get_claims(ctx: AppContext, session_id: str) -> list[dict]`

**Lines:** 119-121

### `def tool_post_finding(ctx: AppContext, session_id: str, expert_role: str, file: str, line_start: int, line_end: int, severity: str, category: str, title: str, actual: str, expected: str, source_ref: str, suggestion_action: str, suggestion_detail: str, confidence: float, snippet: str='', tags: list[str] | None=None, related_findings: list[str] | None=None, agent_id: str='unknown') -> dict`

**Lines:** 124-191

### `def tool_get_findings(ctx: AppContext, session_id: str, *, severity: str | None=None, category: str | None=None, status: str | None=None, file: str | None=None, expert_role: str | None=None, min_confidence: float | None=None, limit: int=0, offset: int=0) -> list[dict]`

**Lines:** 194-212

### `def tool_react(ctx: AppContext, session_id: str, expert_role: str, finding_id: str, reaction: str, reason: str, related_finding_id: str='', agent_id: str='unknown') -> dict`

**Lines:** 215-237

### `def tool_get_summary(ctx: AppContext, session_id: str, fmt: str | None=None) -> str`

Generate summary report.

The MCP schema exposes this as 'format'; internally we use 'fmt'
to avoid shadowing the Python builtin format().

**Lines:** 240-251

### `def tool_orchestrate_review(ctx: AppContext, project_path: str, scope: str='', task: str='', max_experts: int=5, session_name: str | None=None) -> dict`

Create a complete review plan and return it as structured JSON.

The calling LLM follows the returned phases step by step.

**Lines:** 254-273

### `def tool_find_duplicates(ctx: AppContext, session_id: str, file: str, line_start: int, line_end: int, title: str) -> list[dict]`

Check for potential duplicate findings before posting.

**Lines:** 276-289

### `def tool_mark_fixed(ctx: AppContext, session_id: str, finding_id: str, fix_ref: str='') -> dict`

Mark a finding as FIXED. Called by fix-agents after applying a patch.

Args:
    finding_id: The finding to mark as fixed.
    fix_ref: Optional reference to the fix (commit hash, PR url, etc.)

**Lines:** 292-327

### `def tool_bulk_update_status(ctx: AppContext, session_id: str, finding_ids: list[str], new_status: str, reason: str='') -> dict`

Update status of multiple findings at once.

Args:
    finding_ids: List of finding IDs to update.
    new_status: New status (fixed, wontfix, open, confirmed, disputed).
    reason: Optional reason for the status change.

**Lines:** 330-364

### `def tool_post_findings_batch(ctx: AppContext, session_id: str, findings: list[dict]) -> list[dict]`

Post multiple findings in one call. Returns list of results.

**Lines:** 367-399

### `def tool_post_comment(ctx: AppContext, session_id: str, finding_id: str, expert_role: str, content: str) -> dict`

Post an inline comment on a finding.

**Lines:** 402-418

### `def tool_get_events(ctx: AppContext, session_id: str, since: str | None=None, event_type: str | None=None) -> list[dict]`

Get session events since a timestamp (polling fallback).

**Lines:** 421-430

### `def tool_send_message(ctx: AppContext, session_id: str, from_agent: str, to_agent: str, content: str, message_type: str='direct', in_reply_to: str='', urgent: bool=False, context: dict | None=None) -> dict`

Send a message to another agent or broadcast to all.

context dict can include finding/file references:
  {"finding_id": "f-abc", "file": "src/x.py", "line_start": 42,
   "line_end": 58, "title": "Race condition"}

**Lines:** 433-469

### `def tool_mark_phase_done(ctx: AppContext, session_id: str, expert_role: str, phase: int) -> dict`

Mark that an agent has completed a phase. Returns barrier status.

**Lines:** 472-478

### `def tool_check_phase_ready(ctx: AppContext, session_id: str, phase: int) -> dict`

Check if a phase can be started (all agents done with previous phase).

**Lines:** 481-486

### `def tool_get_phase_status(ctx: AppContext, session_id: str) -> dict`

Get full phase status for all agents.

**Lines:** 489-492

### `def tool_get_inbox(ctx: AppContext, session_id: str, expert_role: str, since: str | None=None, message_type: str | None=None) -> list[dict]`

Get messages for a specific agent (their inbox).

**Lines:** 495-505

### `def tool_get_thread(ctx: AppContext, session_id: str, message_id: str) -> list[dict]`

Get a query and all its responses.

**Lines:** 508-515

### `def tool_broadcast(ctx: AppContext, session_id: str, from_agent: str, content: str) -> dict`

Broadcast a message to all agents in the session.

Thin wrapper around tool_send_message with message_type='broadcast'.

**Lines:** 518-530

### `def create_mcp_server()`

Create and configure the MCP server with all 26 tools.

**Lines:** 577-1091
