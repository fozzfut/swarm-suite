"""Tests for the flow DSL: parser, validator, execution state, store."""

from __future__ import annotations

import json

import pytest

from swarm_kb.dsl import (
    AtomNode,
    FlowExecution,
    FlowStore,
    FlowSyntaxError,
    GateNode,
    ParallelNode,
    SequenceNode,
    parse_flow,
    validate_flow,
)


# ---------- parser -----------------------------------------------------------


def test_parse_single_atom():
    ast = parse_flow("review")
    assert isinstance(ast, AtomNode)
    assert ast.name == "review"


def test_parse_sequence():
    ast = parse_flow("a -> b -> c")
    assert isinstance(ast, SequenceNode)
    names = [c.name for c in ast.children if isinstance(c, AtomNode)]
    assert names == ["a", "b", "c"]


def test_parse_parallel():
    ast = parse_flow("a, b, c")
    assert isinstance(ast, ParallelNode)
    names = [c.name for c in ast.children if isinstance(c, AtomNode)]
    assert names == ["a", "b", "c"]


def test_parse_mixed_sequence_and_parallel():
    ast = parse_flow("a -> b, c -> d")
    # Sequence: a, (b||c), d
    assert isinstance(ast, SequenceNode)
    assert isinstance(ast.children[0], AtomNode) and ast.children[0].name == "a"
    assert isinstance(ast.children[1], ParallelNode)
    assert isinstance(ast.children[2], AtomNode) and ast.children[2].name == "d"


def test_parse_groups_with_parens():
    ast = parse_flow("(a, b) -> (c, d)")
    assert isinstance(ast, SequenceNode)
    assert all(isinstance(c, ParallelNode) for c in ast.children)


def test_parse_gate():
    ast = parse_flow("a -> H -> b")
    assert isinstance(ast, SequenceNode)
    assert isinstance(ast.children[1], GateNode)


def test_parse_empty_raises():
    with pytest.raises(FlowSyntaxError, match="empty"):
        parse_flow("")
    with pytest.raises(FlowSyntaxError, match="empty"):
        parse_flow("   ")


def test_parse_dangling_arrow_raises():
    with pytest.raises(FlowSyntaxError):
        parse_flow("a ->")


def test_parse_unbalanced_paren_raises():
    with pytest.raises(FlowSyntaxError):
        parse_flow("(a, b")


def test_parse_unknown_char_raises():
    with pytest.raises(FlowSyntaxError):
        parse_flow("a @ b")


def test_parse_atoms_iter():
    ast = parse_flow("a -> (b, c) -> d")
    names = [a.name for a in ast.iter_atoms()]
    assert sorted(names) == ["a", "b", "c", "d"]


# ---------- validator --------------------------------------------------------


def test_validate_unknown_name_reported():
    ast = parse_flow("a -> b -> c")
    problems = validate_flow(ast, known_names={"a", "c"})
    assert len(problems) == 1
    assert "'b'" in problems[0]


def test_validate_no_known_names_means_no_check():
    ast = parse_flow("anything_at_all")
    assert validate_flow(ast, known_names=None) == []


def test_validate_gate_always_valid():
    ast = parse_flow("a -> H -> b")
    assert validate_flow(ast, known_names={"a", "b"}) == []


# ---------- FlowExecution: cursor through the AST ----------------------------


def test_pending_steps_for_sequence_only_first():
    flow = FlowExecution(source="a -> b -> c", root=parse_flow("a -> b -> c"))
    pending = flow.next_steps()
    assert len(pending) == 1
    assert isinstance(pending[0], AtomNode)
    assert pending[0].name == "a"


def test_pending_steps_for_parallel_all_at_once():
    flow = FlowExecution(source="a, b, c", root=parse_flow("a, b, c"))
    pending = flow.next_steps()
    names = sorted(n.name for n in pending if isinstance(n, AtomNode))
    assert names == ["a", "b", "c"]


def test_mark_done_advances_sequence():
    flow = FlowExecution(source="a -> b", root=parse_flow("a -> b"))
    first = flow.next_steps()[0]
    flow.mark_done(first.id)
    pending = flow.next_steps()
    assert len(pending) == 1
    assert isinstance(pending[0], AtomNode) and pending[0].name == "b"


def test_mark_done_completes_flow():
    flow = FlowExecution(source="a", root=parse_flow("a"))
    only = flow.next_steps()[0]
    flow.mark_done(only.id)
    assert flow.status == "completed"
    assert flow.next_steps() == []


def test_mark_done_idempotent():
    flow = FlowExecution(source="a -> b", root=parse_flow("a -> b"))
    first = flow.next_steps()[0]
    rec1 = flow.mark_done(first.id)
    rec2 = flow.mark_done(first.id)
    assert rec1.step_id == rec2.step_id
    assert rec1.completed_at == rec2.completed_at
    # b should still be pending exactly once.
    pending = flow.next_steps()
    assert len(pending) == 1


def test_mark_done_unknown_step_raises():
    flow = FlowExecution(source="a", root=parse_flow("a"))
    with pytest.raises(ValueError, match="not in this flow"):
        flow.mark_done("step-doesnotexist")


def test_mark_done_out_of_order_raises():
    flow = FlowExecution(source="a -> b", root=parse_flow("a -> b"))
    second = list(flow.root.iter_atoms())[1]
    with pytest.raises(ValueError, match="not pending"):
        flow.mark_done(second.id)


def test_mark_done_structural_node_raises():
    ast = parse_flow("a -> b")
    flow = FlowExecution(source="a -> b", root=ast)
    with pytest.raises(ValueError, match="structural"):
        flow.mark_done(ast.id)  # the SequenceNode itself


def test_parallel_completion_in_any_order():
    flow = FlowExecution(source="a, b -> c", root=parse_flow("a, b -> c"))
    pending_initial = sorted(n.name for n in flow.next_steps())
    assert pending_initial == ["a", "b"]
    # complete b first
    b = next(n for n in flow.next_steps() if isinstance(n, AtomNode) and n.name == "b")
    flow.mark_done(b.id)
    pending_after_b = sorted(n.name for n in flow.next_steps())
    assert pending_after_b == ["a"]
    a = flow.next_steps()[0]
    flow.mark_done(a.id)
    # now c is pending
    pending_after_a = [n.name for n in flow.next_steps() if isinstance(n, AtomNode)]
    assert pending_after_a == ["c"]


def test_gate_appears_in_pending():
    ast = parse_flow("a -> H -> b")
    flow = FlowExecution(source="a -> H -> b", root=ast)
    a = flow.next_steps()[0]
    flow.mark_done(a.id)
    pending = flow.next_steps()
    assert len(pending) == 1
    assert isinstance(pending[0], GateNode)


def test_gate_marked_done_releases_next_step():
    ast = parse_flow("a -> H -> b")
    flow = FlowExecution(source="a -> H -> b", root=ast)
    a = flow.next_steps()[0]
    flow.mark_done(a.id)
    gate = flow.next_steps()[0]
    flow.mark_done(gate.id)
    pending = flow.next_steps()
    assert len(pending) == 1 and isinstance(pending[0], AtomNode) and pending[0].name == "b"


# ---------- FlowStore: persistence -------------------------------------------


def test_store_persists_flow(tmp_path):
    store = FlowStore(tmp_path)
    flow = store.start(source="a -> b")
    raw = json.loads((tmp_path / flow.id / "flow.json").read_text(encoding="utf-8"))
    assert raw["source"] == "a -> b"
    assert raw["status"] == "open"
    assert raw["schema_version"] == 1


def test_store_validates_known_names(tmp_path):
    store = FlowStore(tmp_path)
    with pytest.raises(FlowSyntaxError, match="validation failed"):
        store.start(source="a -> bad", known_names={"a", "b"})


def test_store_round_trips_via_disk(tmp_path):
    store = FlowStore(tmp_path)
    flow = store.start(source="a -> b -> c")
    first = flow.next_steps()[0]
    store.mark_done(flow.id, first.id, outputs={"k": "v"})

    fresh = FlowStore(tmp_path)
    reloaded = fresh.get(flow.id)
    assert reloaded.source == "a -> b -> c"
    assert len(reloaded.completed) == 1
    assert reloaded.completed[0].outputs == {"k": "v"}
    pending_names = [n.name for n in reloaded.next_steps() if isinstance(n, AtomNode)]
    assert pending_names == ["b"]


def test_store_completed_after_all_steps(tmp_path):
    store = FlowStore(tmp_path)
    flow = store.start(source="a, b")
    for n in list(flow.next_steps()):
        store.mark_done(flow.id, n.id)
    final = store.get(flow.id)
    assert final.status == "completed"
    assert final.next_steps() == []


def test_store_cancel_stops_progression(tmp_path):
    store = FlowStore(tmp_path)
    flow = store.start(source="a -> b")
    store.cancel(flow.id)
    cancelled = store.get(flow.id)
    assert cancelled.status == "cancelled"
    # Cannot mark done on cancelled flow.
    a = list(cancelled.root.iter_atoms())[0]
    with pytest.raises(ValueError, match="not open"):
        store.mark_done(flow.id, a.id)


def test_store_list_filters_by_status(tmp_path):
    store = FlowStore(tmp_path)
    f1 = store.start(source="a")
    f2 = store.start(source="b")
    only = list(f2.next_steps())[0]
    store.mark_done(f2.id, only.id)
    open_only = store.list_all(status="open")
    completed_only = store.list_all(status="completed")
    assert {f.id for f in open_only} == {f1.id}
    assert {f.id for f in completed_only} == {f2.id}
