"""AgentRearrange-style flow DSL -- declarative pipeline routing.

Inspired by kyegomez/swarms' einsum-style flow strings (`a -> b, c -> d`).
The DSL describes WHICH agents/tools the AI client should invoke and in
WHAT ORDER, without hardcoding the pipeline stages in Python.

Grammar (compact BNF):

    flow     := sequence
    sequence := parallel ("->" parallel)*
    parallel := atomic ("," atomic)*
    atomic   := name | gate | "(" sequence ")"
    name     := [a-zA-Z_][a-zA-Z0-9_-]*
    gate     := "H"

Semantics:

    "->" is sequence: left-to-right, MUST complete left before right.
    ","  is parallel: every branch may run concurrently at this level.
    "H"  is a human gate -- equivalent to kb_advance_pipeline; the
         executor MUST stop and wait for explicit user advancement.
    "()" groups -- `(a, b) -> c` runs a||b, then c.

Examples:

    review -> fix -> verify -> doc           # standard sequence
    arch -> H -> review                      # arch, gate, review
    lint, type_check -> test -> deploy       # parallel tools, then sequence
    review -> (security_audit, perf_audit) -> fix

The module's job is to parse, validate, and track *progress* through a
flow -- not to execute. swarm-kb is a coordinator, not a runtime; the
AI client consumes `kb_get_next_steps(flow_id)` and dispatches the
named tools itself, then reports back via `kb_mark_step_done`.

Storage: `<kb_root>/flows/<id>/flow.json` (atomic write).

CONCURRENCY (READ THIS BEFORE TOUCHING):
Single-process ownership only. Same load+mutate+atomic_write_text
pattern as CompletionStore / VerificationStore / PgveStore. Two
processes hitting the same flow race -- last-write-wins on the file,
with logical updates lost. Cross-process safety via portalocker on a
sibling .lock is the planned remedy if multi-process orchestrators
become a real deployment scenario.

LIMITS (enterprise input bounds):
  * MAX_SOURCE_LEN guards against DoS via huge DSL strings.
  * MAX_NODES guards against pathological flat sequences.
  * Recursion depth guarded by tracking parse depth -- fail fast at
    MAX_PARSE_DEPTH instead of relying on Python's stack limit.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from swarm_core.io import atomic_write_text

from ._filelock import cross_process_lock, lock_path_for
from ._limits import (
    DEFAULT_MAX_RECORDS,
    MAX_TEXT_LEN,
    BoundedRecordCache,
    check_payload_size,
    check_text,
)

_log = logging.getLogger("swarm_kb.dsl")


FLOW_SCHEMA_VERSION = 1
GATE_TOKEN = "H"

# Parser bounds. Selected to handle every realistic pipeline (3-15 steps,
# 1-2 levels of nesting) with comfortable headroom while rejecting hostile
# input that could OOM or stack-overflow the server.
MAX_SOURCE_LEN: int = 16_384
MAX_NODES: int = 512
MAX_PARSE_DEPTH: int = 64


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass
class FlowNode:
    """Base AST node. `id` is assigned at parse time so the state
    tracker can refer to a specific step independently of its position
    in the source string. Subclasses override `kind` and the iteration
    helpers."""

    id: str = ""
    kind: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "step-" + secrets.token_hex(3)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind}

    def iter_atoms(self) -> Iterator["AtomNode"]:
        return iter([])

    def named_steps(self) -> Iterator[str]:
        for atom in self.iter_atoms():
            if isinstance(atom, AtomNode):
                yield atom.name


@dataclass
class AtomNode(FlowNode):
    """A named tool/agent invocation."""

    name: str = ""
    kind: str = "atom"

    def to_dict(self) -> dict:
        return {**super().to_dict(), "name": self.name}

    def iter_atoms(self) -> Iterator["AtomNode"]:
        yield self


@dataclass
class GateNode(FlowNode):
    """A human-in-loop gate (the `H` token)."""

    kind: str = "gate"

    def iter_atoms(self) -> Iterator["AtomNode"]:
        return iter([])


@dataclass
class SequenceNode(FlowNode):
    """Sequential composition: each child must complete before the next."""

    children: list["FlowNode"] = field(default_factory=list)
    kind: str = "sequence"

    def to_dict(self) -> dict:
        return {**super().to_dict(), "children": [c.to_dict() for c in self.children]}

    def iter_atoms(self) -> Iterator["AtomNode"]:
        for c in self.children:
            yield from c.iter_atoms()


@dataclass
class ParallelNode(FlowNode):
    """Parallel composition: all children may run concurrently."""

    children: list["FlowNode"] = field(default_factory=list)
    kind: str = "parallel"

    def to_dict(self) -> dict:
        return {**super().to_dict(), "children": [c.to_dict() for c in self.children]}

    def iter_atoms(self) -> Iterator["AtomNode"]:
        for c in self.children:
            yield from c.iter_atoms()


def _node_from_dict(d: dict) -> FlowNode:
    """Inverse of FlowNode.to_dict; reconstructs the typed AST."""
    kind = d.get("kind", "")
    nid = d.get("id", "")
    if kind == "atom":
        return AtomNode(id=nid, name=d.get("name", ""))
    if kind == "gate":
        return GateNode(id=nid)
    if kind == "sequence":
        return SequenceNode(
            id=nid,
            children=[_node_from_dict(c) for c in d.get("children", [])],
        )
    if kind == "parallel":
        return ParallelNode(
            id=nid,
            children=[_node_from_dict(c) for c in d.get("children", [])],
        )
    raise ValueError(f"unknown FlowNode kind {kind!r}")


# ---------------------------------------------------------------------------
# Tokenizer + Parser
# ---------------------------------------------------------------------------


class FlowSyntaxError(ValueError):
    """Raised for any DSL parse failure. Inherits ValueError so the MCP
    error wrapper maps it to INVALID_PARAMS."""


_TOKEN_RE = re.compile(
    r"\s*(?:(->)|(,)|(\()|(\))|([A-Za-z_][A-Za-z0-9_-]*))"
)


def _tokenize(src: str) -> list[tuple[str, str]]:
    """Return a list of (kind, text) tokens.

    Kinds: 'arrow', 'comma', 'lparen', 'rparen', 'name'. Whitespace is
    skipped. Unknown characters raise FlowSyntaxError pointing at the
    offending position. Pure-whitespace input returns an empty list
    (the parser then raises an "empty flow" error).
    """
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(src):
        # Skip whitespace explicitly so "all whitespace remaining"
        # exits cleanly instead of falling into the regex no-match path.
        while pos < len(src) and src[pos].isspace():
            pos += 1
        if pos >= len(src):
            break
        m = _TOKEN_RE.match(src, pos)
        if not m or m.start() < pos:
            raise FlowSyntaxError(
                f"unexpected character at position {pos}: {src[pos]!r}"
            )
        new_pos = m.end()
        if new_pos == pos:
            break
        groups = m.groups()
        if groups[0]:
            tokens.append(("arrow", groups[0]))
        elif groups[1]:
            tokens.append(("comma", groups[1]))
        elif groups[2]:
            tokens.append(("lparen", groups[2]))
        elif groups[3]:
            tokens.append(("rparen", groups[3]))
        elif groups[4]:
            tokens.append(("name", groups[4]))
        pos = new_pos
    return tokens


class _Parser:
    """Recursive-descent parser for the flow DSL.

    Precedence (loosest first):
        sequence  ->   (left-associative)
        parallel  ,
        atomic    name | gate | (sequence)
    """

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._depth = 0
        self._node_count = 0

    def parse(self) -> FlowNode:
        if not self._tokens:
            raise FlowSyntaxError("empty flow")
        node = self._parse_sequence()
        if self._pos != len(self._tokens):
            kind, text = self._tokens[self._pos]
            raise FlowSyntaxError(
                f"unexpected token {text!r} (kind={kind}) at position {self._pos}"
            )
        return node

    def _bump_node(self) -> None:
        self._node_count += 1
        if self._node_count > MAX_NODES:
            raise FlowSyntaxError(
                f"flow has too many nodes (>{MAX_NODES}); split into smaller flows"
            )

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_PARSE_DEPTH:
            raise FlowSyntaxError(
                f"flow nesting too deep (>{MAX_PARSE_DEPTH} levels)"
            )

    def _leave(self) -> None:
        self._depth -= 1

    # -- helpers ---------------------------------------------------------

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _eat(self, kind: str) -> str:
        tok = self._peek()
        if tok is None or tok[0] != kind:
            seen = tok[0] if tok else "EOF"
            raise FlowSyntaxError(f"expected {kind}, saw {seen}")
        self._pos += 1
        return tok[1]

    # -- grammar productions --------------------------------------------

    def _parse_sequence(self) -> FlowNode:
        self._enter()
        try:
            first = self._parse_parallel()
            children = [first]
            while self._peek() and self._peek()[0] == "arrow":
                self._eat("arrow")
                children.append(self._parse_parallel())
            if len(children) == 1:
                return first
            self._bump_node()
            return SequenceNode(children=children)
        finally:
            self._leave()

    def _parse_parallel(self) -> FlowNode:
        self._enter()
        try:
            first = self._parse_atomic()
            children = [first]
            while self._peek() and self._peek()[0] == "comma":
                self._eat("comma")
                children.append(self._parse_atomic())
            if len(children) == 1:
                return first
            self._bump_node()
            return ParallelNode(children=children)
        finally:
            self._leave()

    def _parse_atomic(self) -> FlowNode:
        tok = self._peek()
        if tok is None:
            raise FlowSyntaxError("unexpected end of flow")
        kind, text = tok
        if kind == "lparen":
            self._enter()
            try:
                self._eat("lparen")
                inner = self._parse_sequence()
                self._eat("rparen")
                return inner
            finally:
                self._leave()
        if kind == "name":
            self._eat("name")
            self._bump_node()
            if text == GATE_TOKEN:
                return GateNode()
            return AtomNode(name=text)
        raise FlowSyntaxError(f"expected name or '(', saw {kind} {text!r}")


def parse_flow(src: str) -> FlowNode:
    """Parse a DSL string into an AST. Raises FlowSyntaxError on any error.

    Bounded by MAX_SOURCE_LEN, MAX_NODES, MAX_PARSE_DEPTH so a hostile
    caller cannot OOM or stack-overflow the server.
    """
    if len(src) > MAX_SOURCE_LEN:
        raise FlowSyntaxError(
            f"flow source length {len(src)} exceeds MAX_SOURCE_LEN={MAX_SOURCE_LEN}"
        )
    return _Parser(_tokenize(src)).parse()


def validate_flow(
    root: FlowNode,
    *,
    known_names: set[str] | None = None,
) -> list[str]:
    """Return a list of validation problems (empty list = OK).

    If `known_names` is provided, every AtomNode's name is checked
    against it -- unknown names produce an error per occurrence. The
    GateNode and structural nodes are always valid.
    """
    problems: list[str] = []
    if known_names is None:
        return problems
    for atom in root.iter_atoms():
        if atom.name not in known_names:
            problems.append(
                f"unknown step name {atom.name!r} (id={atom.id})"
            )
    return problems


# ---------------------------------------------------------------------------
# Flow execution state -- cursor through the AST
# ---------------------------------------------------------------------------


@dataclass
class StepRecord:
    """One completed step in a flow execution."""

    step_id: str = ""
    name: str = ""
    completed_at: str = ""
    outputs: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.completed_at:
            self.completed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "completed_at": self.completed_at,
            "outputs": dict(self.outputs),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StepRecord":
        return cls(
            step_id=d.get("step_id", ""),
            name=d.get("name", ""),
            completed_at=d.get("completed_at", ""),
            outputs=dict(d.get("outputs", {})),
        )


@dataclass
class FlowExecution:
    """One in-flight flow with its AST and progress cursor.

    Pending step set tells the AI client which steps it MAY do next.
    For sequence: only the leftmost not-yet-done child is pending. For
    parallel: every not-yet-done child is pending. Gates are pending
    too -- the client signals the human and waits for kb_advance_flow.
    """

    id: str = ""
    source: str = ""
    root: Optional[FlowNode] = None
    completed: list[StepRecord] = field(default_factory=list)
    status: str = "open"          # open|completed|cancelled
    project_path: str = ""
    source_tool: str = ""
    source_session: str = ""
    schema_version: int = FLOW_SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "flow-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    # -- view ------------------------------------------------------------

    def completed_step_ids(self) -> set[str]:
        return {r.step_id for r in self.completed}

    def next_steps(self) -> list[FlowNode]:
        """Return the AST nodes the client may execute next.

        Gates are returned just like atoms; the client distinguishes
        and surfaces a human prompt, then calls mark_step_done with
        the gate's id once the human confirms.
        """
        if self.root is None or self.status != "open":
            return []
        return list(_pending(self.root, self.completed_step_ids()))

    def is_complete(self) -> bool:
        return self.root is not None and not self.next_steps() and self.status == "open"

    # -- mutation --------------------------------------------------------

    def mark_done(self, step_id: str, outputs: dict | None = None) -> StepRecord:
        if self.root is None:
            raise ValueError("flow has no root AST")
        if self.status != "open":
            raise ValueError(f"flow {self.id!r} is not open (status={self.status})")
        node = _find_node(self.root, step_id)
        if node is None:
            raise ValueError(f"step {step_id!r} not in this flow")
        if not isinstance(node, (AtomNode, GateNode)):
            raise ValueError(
                f"step {step_id!r} is a structural node ({node.kind}); "
                "only atoms/gates can be marked done"
            )
        if step_id in self.completed_step_ids():
            # Idempotent: re-mark returns the existing record.
            for r in self.completed:
                if r.step_id == step_id:
                    return StepRecord.from_dict(r.to_dict())
        pending_ids = {n.id for n in self.next_steps()}
        if step_id not in pending_ids:
            raise ValueError(
                f"step {step_id!r} is not pending; pending: {sorted(pending_ids)}"
            )
        rec = StepRecord(
            step_id=step_id,
            name=node.name if isinstance(node, AtomNode) else GATE_TOKEN,
            outputs=dict(outputs or {}),
        )
        self.completed.append(rec)
        # Auto-finish if no more pending steps.
        if not self.next_steps():
            self.status = "completed"
        return StepRecord.from_dict(rec.to_dict())

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "source": self.source,
            "root": self.root.to_dict() if self.root else None,
            "completed": [r.to_dict() for r in self.completed],
            "status": self.status,
            "project_path": self.project_path,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FlowExecution":
        root_raw = d.get("root")
        root = _node_from_dict(root_raw) if root_raw else None
        # Per CLAUDE.md schema-versioning: unknown status -> "open" + warn.
        raw_status = d.get("status", "open")
        if raw_status not in VALID_FLOW_STATUSES:
            _log.warning(
                "FlowExecution %s: unknown status %r; falling back to 'open'",
                d.get("id", "?"), raw_status,
            )
            status = "open"
        else:
            status = raw_status
        v = int(d.get("schema_version", FLOW_SCHEMA_VERSION))
        if v > FLOW_SCHEMA_VERSION:
            _log.warning(
                "FlowExecution %s schema_version %d > current %d; reading what we understand",
                d.get("id", "?"), v, FLOW_SCHEMA_VERSION,
            )
        return cls(
            schema_version=v,
            id=d.get("id", ""),
            source=d.get("source", ""),
            root=root,
            completed=[StepRecord.from_dict(r) for r in d.get("completed", [])],
            status=status,
            project_path=d.get("project_path", ""),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            created_at=d.get("created_at", ""),
        )


def _pending(node: FlowNode, done: set[str]) -> Iterator[FlowNode]:
    """Yield the next executable nodes given the set of completed step ids."""
    if isinstance(node, (AtomNode, GateNode)):
        if node.id not in done:
            yield node
        return
    if isinstance(node, SequenceNode):
        for child in node.children:
            child_pending = list(_pending(child, done))
            if child_pending:
                # Block on the first not-yet-done child.
                yield from child_pending
                return
        return
    if isinstance(node, ParallelNode):
        for child in node.children:
            yield from _pending(child, done)
        return


def _find_node(root: FlowNode, target_id: str) -> Optional[FlowNode]:
    if root.id == target_id:
        return root
    for child_attr in ("children",):
        children = getattr(root, child_attr, None)
        if not children:
            continue
        for c in children:
            found = _find_node(c, target_id)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


VALID_FLOW_STATUSES: tuple[str, ...] = ("open", "completed", "cancelled")


class FlowStore:
    """File-backed registry of FlowExecution aggregates."""

    def __init__(
        self,
        root: Path,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        self._root = Path(root)
        self._flows: BoundedRecordCache[FlowExecution] = BoundedRecordCache(max_records)
        self._lock = threading.RLock()
        self._load_all()

    def start(
        self,
        *,
        source: str,
        known_names: set[str] | None = None,
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
    ) -> FlowExecution:
        ast = parse_flow(source)
        problems = validate_flow(ast, known_names=known_names)
        if problems:
            raise FlowSyntaxError(
                "flow validation failed: " + "; ".join(problems)
            )
        flow = FlowExecution(
            source=source,
            root=ast,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        with self._lock:
            self._flows.put(flow.id, flow)
            self._save(flow.id)
        _log.info("Started flow %s: %s", flow.id, source)
        return flow

    def mark_done(
        self,
        flow_id: str,
        step_id: str,
        outputs: dict | None = None,
    ) -> StepRecord:
        with self._lock, cross_process_lock(self._lock_for(flow_id)):
            f = self._force_reload(flow_id)
            if f is None:
                raise ValueError(f"Flow {flow_id!r} not found")
            rec = f.mark_done(step_id, outputs)
            self._save(flow_id)
        return rec

    def cancel(self, flow_id: str) -> None:
        with self._lock, cross_process_lock(self._lock_for(flow_id)):
            f = self._force_reload(flow_id)
            if f is None:
                raise ValueError(f"Flow {flow_id!r} not found")
            if f.status != "open":
                raise ValueError(
                    f"Flow {flow_id!r} is not open (status={f.status})"
                )
            f.status = "cancelled"
            self._save(flow_id)

    # -- cross-process lock helpers --------------------------------------

    def _lock_for(self, flow_id: str) -> Path:
        return lock_path_for(self._root / flow_id / "flow.json")

    def _force_reload(self, flow_id: str) -> Optional[FlowExecution]:
        """Read the record straight from disk, bypassing the cache."""
        path = self._root / flow_id / "flow.json"
        if not path.exists():
            self._flows.pop(flow_id)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            f = FlowExecution.from_dict(data)
            self._flows.put(f.id, f)
            return f
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot reload flow %s: %s", flow_id, exc)
            return None

    def get(self, flow_id: str) -> Optional[FlowExecution]:
        with self._lock:
            f = self._get_or_load(flow_id)
            return copy.deepcopy(f) if f else None

    def list_all(
        self,
        *,
        status: str = "",
        source_tool: str = "",
    ) -> list[FlowExecution]:
        with self._lock:
            self._refresh_from_disk()
            results = list(self._flows.values())
            if status:
                results = [f for f in results if f.status == status]
            if source_tool:
                results = [f for f in results if f.source_tool == source_tool]
            return [copy.deepcopy(f) for f in results]

    # -- internals -------------------------------------------------------

    def _get_or_load(self, flow_id: str) -> Optional[FlowExecution]:
        existing = self._flows.get(flow_id)
        if existing is not None:
            return existing
        path = self._root / flow_id / "flow.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            f = FlowExecution.from_dict(data)
            self._flows.put(f.id, f)
            return f
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot load flow %s: %s", flow_id, exc)
            return None

    def _refresh_from_disk(self) -> None:
        if not self._root.exists():
            return
        for entry in self._root.iterdir():
            if not entry.is_dir() or entry.name in self._flows:
                continue
            path = entry / "flow.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                f = FlowExecution.from_dict(data)
                self._flows.put(f.id, f)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                _log.warning("Skipping corrupt flow in %s: %s", entry, exc)

    def _save(self, flow_id: str) -> None:
        f = self._flows.get(flow_id)
        if f is None:
            return
        target = self._root / flow_id / "flow.json"
        atomic_write_text(target, json.dumps(f.to_dict(), indent=2, ensure_ascii=False))

    def _load_all(self) -> None:
        if not self._root.exists():
            return
        with self._lock:
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir():
                    continue
                path = entry / "flow.json"
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    f = FlowExecution.from_dict(data)
                    self._flows.put(f.id, f)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    _log.warning("Skipping corrupt flow in %s: %s", entry, exc)
