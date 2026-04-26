---
title: Message Bus
type: api
status: draft
source_files:
- src/review_swarm/message_bus.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/message_bus.py
lines_of_code: 330
classes:
- MessageBus
functions: []
---

# Message Bus

MessageBus -- agent-to-agent communication with routing, read-tracking, and pending notifications.

**Source:** `src/review_swarm/message_bus.py` | **Lines:** 330

## Dependencies

- `__future__`
- `collections`
- `json`
- `logging_config`
- `models`
- `pathlib`
- `threading`

## Classes

### `class MessageBus`

Per-session message bus for direct, broadcast, and query/response messaging.

Topology: full mesh via hub (star). Every agent connects to the bus.
- DIRECT:    routed to one specific agent's inbox
- BROADCAST: routed to ALL agents' inboxes (except sender)
- QUERY:     broadcast + tracked for responses (auto-urgent)
- RESPONSE:  routed to the original query sender

Read-tracking:
  Each agent has a read watermark (timestamp). Messages after the
  watermark are "unread". The get_pending() method returns a compact
  summary suitable for piggyback injection into any tool response.

Messages are persisted to messages.jsonl.

**Lines:** 16-330

**Methods:**

- `def register_agent(self, expert_role: str) -> None` — Register an agent so it can receive broadcasts and queries.
- `def unregister_agent(self, expert_role: str) -> None`
- `def registered_agents(self) -> set[str]`
- `def send(self, message: Message) -> Message` — Send a message. Routes to appropriate inbox(es) based on type.
- `def send_direct(self, session_id: str, from_agent: str, to_agent: str, content: str, urgent: bool=False) -> Message` — Convenience: send a direct message.
- `def send_broadcast(self, session_id: str, from_agent: str, content: str, urgent: bool=False) -> Message` — Convenience: broadcast a message to all agents.
- `def send_query(self, session_id: str, from_agent: str, content: str) -> Message` — Convenience: broadcast a query that expects responses.
- `def send_response(self, session_id: str, from_agent: str, in_reply_to: str, content: str) -> Message` — Convenience: respond to a query.
- `def get_inbox(self, expert_role: str, since: str | None=None, message_type: str | None=None) -> list[dict]` — Get messages for a specific agent (their inbox).
- `def mark_read(self, expert_role: str) -> None` — Explicitly mark all messages as read for this agent.
- `def get_pending(self, expert_role: str, max_preview: int=3) -> dict` — Get pending (unread) message summary for piggyback injection.
- `def get_thread(self, message_id: str) -> list[dict]` — Get a query and all its responses (conversation thread).
- `def get_all_messages(self, since: str | None=None, message_type: str | None=None) -> list[dict]` — Get all messages (global view), optionally filtered.
- `def message_count(self) -> int`
