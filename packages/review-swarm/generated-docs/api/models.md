---
title: Models
type: api
status: draft
source_files:
- src/review_swarm/models.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/models.py
lines_of_code: 436
classes:
- Severity
- Category
- Action
- Status
- ClaimStatus
- ReactionType
- ReactionDict
- CommentDict
- Finding
- Claim
- Reaction
- EventType
- Event
- MessageType
- Message
functions:
- now_iso
---

# Models

Data models for ReviewSwarm -- Finding, Claim, Reaction with serialization.

**Source:** `src/review_swarm/models.py` | **Lines:** 436

## Dependencies

- `__future__`
- `dataclasses`
- `datetime`
- `enum`
- `secrets`
- `typing`

## Classes

### `class Severity(str, Enum)`

**Lines:** 23-28

### `class Category(str, Enum)`

**Lines:** 31-38

### `class Action(str, Enum)`

**Lines:** 41-45

### `class Status(str, Enum)`

**Lines:** 48-54

### `class ClaimStatus(str, Enum)`

**Lines:** 57-60

### `class ReactionType(str, Enum)`

**Lines:** 63-67

### `class ReactionDict(TypedDict)`

Expected schema for reaction dicts stored in Finding.reactions.

**Lines:** 73-84

### `class CommentDict(TypedDict)`

Expected schema for comment dicts stored in Finding.comments.

**Lines:** 87-92

### `class Finding`

A code review finding reported by an expert agent.

**Lines:** 99-198

**Methods:**

- `def generate_id() -> str` — Generate a finding ID: 'f-' + 6 hex chars (8 chars total).
- `def to_dict(self) -> dict` — Serialize to a plain dict (enums become their string values).
- `def from_dict(cls, d: dict) -> Finding` — Deserialize from a plain dict.

### `class Claim`

A file claim by an expert agent (prevents duplicate work).

**Lines:** 205-263

**Methods:**

- `def is_expired(self) -> bool` — Check if this claim has expired based on claimed_at + ttl_seconds.
- `def generate_id() -> str` — Generate a claim ID: 'c-' + 6 hex chars (8 chars total).
- `def to_dict(self) -> dict` — Serialize to a plain dict.
- `def from_dict(cls, d: dict) -> Claim` — Deserialize from a plain dict.

### `class Reaction`

A reaction to a finding by another expert agent.

**Lines:** 270-317

**Methods:**

- `def to_dict(self) -> dict` — Serialize to a plain dict.
- `def from_dict(cls, d: dict) -> Reaction` — Deserialize from a plain dict.

### `class EventType(str, Enum)`

**Lines:** 323-332

### `class Event`

A real-time event published when session state changes.

**Lines:** 336-367

**Methods:**

- `def generate_id() -> str` — Generate an event ID: 'e-' + 8 hex chars.
- `def to_dict(self) -> dict`
- `def from_dict(cls, d: dict) -> Event`

### `class MessageType(str, Enum)`

**Lines:** 373-377

### `class Message`

Agent-to-agent message for active coordination.

**Lines:** 381-436

**Methods:**

- `def generate_id() -> str`
- `def to_dict(self) -> dict`
- `def from_dict(cls, d: dict) -> Message`

## Functions

### `def now_iso() -> str`

Return current UTC time as ISO 8601 string.

**Lines:** 15-17
