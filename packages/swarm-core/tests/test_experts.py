"""Tests for ExpertRegistry + suggest strategies."""

from pathlib import Path

import pytest

from swarm_core.experts import (
    ExpertRegistry,
    ProjectScanStrategy,
    FindingMatchStrategy,
    NullSuggestStrategy,
)


def _write_yaml(p: Path, name: str, body: dict | None = None) -> None:
    import yaml
    body = body or {}
    body.setdefault("name", name)
    body.setdefault("description", f"{name} description")
    body.setdefault("system_prompt", "stub")
    p.write_text(yaml.safe_dump(body), encoding="utf-8")


def test_registry_loads_yaml_profiles(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_yaml(builtin / "alpha.yaml", "Alpha")
    _write_yaml(builtin / "beta.yaml", "Beta")

    reg = ExpertRegistry(builtin_dir=builtin)
    profiles = reg.list_profiles()
    assert {p.slug for p in profiles} == {"alpha", "beta"}


def test_registry_skips_corrupt_yaml(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_yaml(builtin / "good.yaml", "Good")
    (builtin / "bad.yaml").write_text("not: : valid: yaml:", encoding="utf-8")

    reg = ExpertRegistry(builtin_dir=builtin)
    slugs = {p.slug for p in reg.list_profiles()}
    assert slugs == {"good"}


def test_registry_custom_dirs_override(tmp_path: Path):
    builtin = tmp_path / "builtin"
    custom = tmp_path / "custom"
    builtin.mkdir()
    custom.mkdir()
    _write_yaml(builtin / "alpha.yaml", "Alpha-Builtin")
    _write_yaml(custom / "alpha.yaml", "Alpha-Custom")

    reg = ExpertRegistry(builtin_dir=builtin, custom_dirs=[custom])
    p = reg.load_profile("alpha")
    assert p.name == "Alpha-Custom"


def test_null_suggest_strategy_returns_empty(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_yaml(builtin / "x.yaml", "X")
    reg = ExpertRegistry(builtin_dir=builtin, suggest_strategy=NullSuggestStrategy())
    assert reg.suggest("/anywhere") == []


def test_finding_match_strategy(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_yaml(builtin / "security-fix.yaml", "Security Fix")
    _write_yaml(builtin / "performance-fix.yaml", "Performance Fix")
    _write_yaml(builtin / "refactoring.yaml", "Refactoring")

    reg = ExpertRegistry(builtin_dir=builtin, suggest_strategy=FindingMatchStrategy())
    findings = [
        {"category": "security", "tags": ["injection"], "title": "SQL injection"},
        {"category": "performance", "tags": [], "title": "N+1 queries"},
    ]
    suggestions = reg.suggest(findings)
    slugs = [s["slug"] for s in suggestions]
    assert "security-fix" in slugs
    assert "performance-fix" in slugs


def test_project_scan_strategy_detects_imports(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "app.py").write_text(
        "import flask\nfrom flask import Flask\n", encoding="utf-8"
    )

    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _write_yaml(builtin / "security.yaml", "Security", body={
        "name": "Security",
        "description": "Security expert",
        "system_prompt": "stub",
        "relevance_signals": {"imports": ["flask"], "patterns": []},
    })

    reg = ExpertRegistry(builtin_dir=builtin, suggest_strategy=ProjectScanStrategy())
    suggestions = reg.suggest(proj)
    assert suggestions
    assert suggestions[0]["slug"] == "security"


def test_project_scan_strategy_rejects_wrong_context_type(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    reg = ExpertRegistry(builtin_dir=builtin, suggest_strategy=ProjectScanStrategy())
    with pytest.raises(TypeError):
        reg.suggest(123)
