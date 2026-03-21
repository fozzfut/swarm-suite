"""MessageBus -- agent-to-agent communication with routing, read-tracking, and pending notifications."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .models import Message, MessageType, now_iso


class MessageBus:
    """Per-session message bus for direct, broadcast, and query/response messaging.

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
    """

    def __init__(self, session_id: str, messages_path: Path) -> None:
        self._session_id = session_id
        self._messages_path = Path(messages_path)
        self._messages: list[Message] = []
        self._inboxes: dict[str, list[Message]] = defaultdict(list)
        self._agents: set[str] = set()
        # Read watermark per agent: ISO timestamp of last read
        self._read_watermarks: dict[str, str] = {}
        self._load()

    # ── Agent registration ───────────────────────────────────────────

    def register_agent(self, expert_role: str) -> None:
        """Register an agent so it can receive broadcasts and queries."""
        self._agents.add(expert_role)

    def unregister_agent(self, expert_role: str) -> None:
        self._agents.discard(expert_role)

    @property
    def registered_agents(self) -> set[str]:
        return set(self._agents)

    # ── Send ─────────────────────────────────────────────────────────

    def send(self, message: Message) -> Message:
        """Send a message. Routes to appropriate inbox(es) based on type."""
        self._messages.append(message)
        self._append_to_disk(message)

        if message.message_type == MessageType.DIRECT:
            self._inboxes[message.to_agent].append(message)

        elif message.message_type in (MessageType.BROADCAST, MessageType.QUERY):
            for agent in self._agents:
                if agent != message.from_agent:
                    self._inboxes[agent].append(message)

        elif message.message_type == MessageType.RESPONSE:
            original = self._find_message(message.in_reply_to)
            if original:
                self._inboxes[original.from_agent].append(message)
            if message.to_agent and message.to_agent != "*":
                if not original or message.to_agent != original.from_agent:
                    self._inboxes[message.to_agent].append(message)

        return message

    def send_direct(
        self, session_id: str, from_agent: str, to_agent: str, content: str,
        urgent: bool = False,
    ) -> Message:
        """Convenience: send a direct message."""
        msg = Message(
            id=Message.generate_id(),
            session_id=session_id,
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.DIRECT,
            content=content,
            urgent=urgent,
        )
        return self.send(msg)

    def send_broadcast(
        self, session_id: str, from_agent: str, content: str,
        urgent: bool = False,
    ) -> Message:
        """Convenience: broadcast a message to all agents."""
        msg = Message(
            id=Message.generate_id(),
            session_id=session_id,
            from_agent=from_agent,
            to_agent="*",
            message_type=MessageType.BROADCAST,
            content=content,
            urgent=urgent,
        )
        return self.send(msg)

    def send_query(
        self, session_id: str, from_agent: str, content: str,
    ) -> Message:
        """Convenience: broadcast a query that expects responses.

        Queries are always urgent -- they need responses to unblock the sender.
        """
        msg = Message(
            id=Message.generate_id(),
            session_id=session_id,
            from_agent=from_agent,
            to_agent="*",
            message_type=MessageType.QUERY,
            content=content,
            urgent=True,  # queries are always urgent
        )
        return self.send(msg)

    def send_response(
        self, session_id: str, from_agent: str, in_reply_to: str, content: str,
    ) -> Message:
        """Convenience: respond to a query."""
        original = self._find_message(in_reply_to)
        to_agent = original.from_agent if original else "*"
        msg = Message(
            id=Message.generate_id(),
            session_id=session_id,
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.RESPONSE,
            content=content,
            in_reply_to=in_reply_to,
        )
        return self.send(msg)

    # ── Read + Pending ───────────────────────────────────────────────

    def get_inbox(
        self,
        expert_role: str,
        since: str | None = None,
        message_type: str | None = None,
    ) -> list[dict]:
        """Get messages for a specific agent (their inbox).

        Calling this advances the read watermark to now.
        """
        msgs = self._inboxes.get(expert_role, [])
        if since:
            msgs = [m for m in msgs if m.created_at > since]
        if message_type:
            mt = MessageType(message_type)
            msgs = [m for m in msgs if m.message_type == mt]
        # Advance read watermark
        self._read_watermarks[expert_role] = now_iso()
        return [m.to_dict() for m in msgs]

    def mark_read(self, expert_role: str) -> None:
        """Explicitly mark all messages as read for this agent."""
        self._read_watermarks[expert_role] = now_iso()

    def get_pending(self, expert_role: str, max_preview: int = 3) -> dict:
        """Get pending (unread) message summary for piggyback injection.

        Returns a compact dict suitable for adding to any tool response:
        {
            "count": 5,
            "urgent": 2,
            "preview": [
                {"id": "m-abc", "from_agent": "api-signatures",
                 "message_type": "query", "content": "...", "urgent": true},
                ...
            ]
        }

        Returns empty dict ({}) if no pending messages.
        """
        watermark = self._read_watermarks.get(expert_role, "")
        inbox = self._inboxes.get(expert_role, [])

        if watermark:
            unread = [m for m in inbox if m.created_at > watermark]
        else:
            unread = list(inbox)

        if not unread:
            return {}

        urgent_count = sum(1 for m in unread if m.urgent)

        # Sort: urgent first, then newest first
        sorted_unread = sorted(
            unread,
            key=lambda m: (not m.urgent, m.created_at),
            reverse=False,
        )
        # Urgent first, then reverse chronological
        urgent_msgs = [m for m in sorted_unread if m.urgent]
        normal_msgs = sorted(
            [m for m in sorted_unread if not m.urgent],
            key=lambda m: m.created_at,
            reverse=True,
        )
        preview_msgs = (urgent_msgs + normal_msgs)[:max_preview]

        preview = []
        for m in preview_msgs:
            preview.append({
                "id": m.id,
                "from_agent": m.from_agent,
                "message_type": m.message_type.value,
                "content": m.content[:200] + ("..." if len(m.content) > 200 else ""),
                "urgent": m.urgent,
            })

        return {
            "count": len(unread),
            "urgent": urgent_count,
            "preview": preview,
        }

    def get_thread(self, message_id: str) -> list[dict]:
        """Get a query and all its responses (conversation thread)."""
        thread = []
        for m in self._messages:
            if m.id == message_id or m.in_reply_to == message_id:
                thread.append(m.to_dict())
        return thread

    def get_all_messages(
        self, since: str | None = None, message_type: str | None = None,
    ) -> list[dict]:
        """Get all messages (global view), optionally filtered."""
        msgs = self._messages
        if since:
            msgs = [m for m in msgs if m.created_at > since]
        if message_type:
            mt = MessageType(message_type)
            msgs = [m for m in msgs if m.message_type == mt]
        return [m.to_dict() for m in msgs]

    def message_count(self) -> int:
        return len(self._messages)

    # ── Persistence ──────────────────────────────────────────────────

    def _find_message(self, message_id: str) -> Message | None:
        for m in self._messages:
            if m.id == message_id:
                return m
        return None

    def _append_to_disk(self, message: Message) -> None:
        self._messages_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._messages_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(message.to_dict()) + "\n")

    def _load(self) -> None:
        if not self._messages_path.exists():
            return
        with open(self._messages_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                msg = Message.from_dict(json.loads(line))
                self._messages.append(msg)
                self._agents.add(msg.from_agent)
                if msg.to_agent and msg.to_agent != "*":
                    self._agents.add(msg.to_agent)
        self._rebuild_inboxes()

    def _rebuild_inboxes(self) -> None:
        """Rebuild in-memory inboxes from the full message list."""
        self._inboxes.clear()
        for msg in self._messages:
            if msg.message_type == MessageType.DIRECT:
                self._inboxes[msg.to_agent].append(msg)
            elif msg.message_type in (MessageType.BROADCAST, MessageType.QUERY):
                for agent in self._agents:
                    if agent != msg.from_agent:
                        self._inboxes[agent].append(msg)
            elif msg.message_type == MessageType.RESPONSE:
                original = self._find_message(msg.in_reply_to)
                if original:
                    self._inboxes[original.from_agent].append(msg)
                if msg.to_agent and msg.to_agent != "*":
                    if not original or msg.to_agent != original.from_agent:
                        self._inboxes[msg.to_agent].append(msg)
