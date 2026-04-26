"""Tests for the debate-format registry and the format field on Debate."""

from __future__ import annotations

import pytest

from swarm_kb.debate_engine import Debate, DebateEngine
from swarm_kb.debate_formats import (
    DebateFormat,
    DebatePhase,
    get_format,
    is_known_format,
    list_formats,
    register_format,
)


def test_default_formats_registered():
    names = list_formats()
    expected = {
        "open", "with_judge", "trial", "mediation",
        "one_on_one", "expert_panel", "round_table", "interview",
        "peer_review", "brainstorming", "council", "mentorship", "negotiation",
    }
    assert expected.issubset(set(names))


def test_all_formats_have_required_fields():
    """Every registered format must have a non-empty summary, actors, phases, and stop_condition."""
    for name in list_formats():
        fmt = get_format(name)
        assert fmt.summary, f"{name} has empty summary"
        assert fmt.actors, f"{name} has no actors"
        assert fmt.phases, f"{name} has no phases"
        assert fmt.stop_condition, f"{name} has empty stop_condition"
        for p in fmt.phases:
            assert p.name, f"{name} has a phase with empty name"
            assert p.actors, f"{name}.{p.name} has no actors"
            assert p.description, f"{name}.{p.name} has empty description"


def test_get_format_returns_spec():
    fmt = get_format("trial")
    assert fmt.actors == ["prosecution", "defense", "judge"]
    assert any(p.name == "ruling" for p in fmt.phases)


def test_get_unknown_format_raises():
    with pytest.raises(ValueError, match="unknown debate format"):
        get_format("kangaroo_court")


def test_register_format_blocks_overwrite_by_default():
    fmt = DebateFormat(
        name="trial",
        summary="x",
        actors=["a"],
        phases=[DebatePhase(name="p", actors=["a"], description="d")],
        stop_condition="x",
    )
    with pytest.raises(ValueError, match="already registered"):
        register_format(fmt)


def test_register_format_overwrite_true_replaces():
    custom = DebateFormat(
        name="custom_test",
        summary="test",
        actors=["a"],
        phases=[DebatePhase(name="p", actors=["a"], description="d")],
        stop_condition="x",
    )
    register_format(custom)
    assert is_known_format("custom_test")
    # Replacement allowed with overwrite=True.
    register_format(custom, overwrite=True)


def test_format_to_dict_round_trip():
    fmt = get_format("with_judge")
    d = fmt.to_dict()
    assert d["name"] == "with_judge"
    assert isinstance(d["phases"], list)
    assert d["phases"][0]["name"]


def test_debate_defaults_to_open_format():
    d = Debate(topic="anything")
    assert d.format == "open"
    rebuilt = Debate.from_dict(d.to_dict())
    assert rebuilt.format == "open"


def test_debate_format_round_trips():
    d = Debate(topic="x", format="trial")
    rebuilt = Debate.from_dict(d.to_dict())
    assert rebuilt.format == "trial"


def test_engine_rejects_unknown_format(tmp_path):
    eng = DebateEngine(tmp_path)
    with pytest.raises(ValueError, match="unknown debate format"):
        eng.start_debate(topic="x", format="not_a_format")


def test_engine_starts_with_named_format(tmp_path):
    eng = DebateEngine(tmp_path)
    d = eng.start_debate(topic="security finding", format="trial")
    assert d.format == "trial"
    # Reloads from disk preserve format.
    eng2 = DebateEngine(tmp_path)
    reloaded = eng2.get_debate(d.id)
    assert reloaded.format == "trial"


def test_legacy_debate_dict_without_format_loads_as_open():
    legacy = {
        "id": "dbt-legacy",
        "topic": "old debate",
        "context": "",
        "project_path": "",
        "source_tool": "",
        "source_session": "",
        "status": "open",
        "proposals": [],
        "critiques": [],
        "votes": [],
        "decision": None,
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    d = Debate.from_dict(legacy)
    assert d.format == "open"


def test_unknown_format_on_load_falls_back_to_open(caplog):
    """Per CLAUDE.md schema-versioning: log warning, normalise to a known value."""
    bad = {
        "id": "dbt-x",
        "topic": "t",
        "context": "",
        "project_path": "",
        "source_tool": "",
        "source_session": "",
        "status": "open",
        "proposals": [],
        "critiques": [],
        "votes": [],
        "decision": None,
        "format": "kangaroo_court",
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    import logging
    with caplog.at_level(logging.WARNING):
        d = Debate.from_dict(bad)
    assert d.format == "open"
    assert any("kangaroo_court" in r.message or "kangaroo_court" in str(r) for r in caplog.records)
