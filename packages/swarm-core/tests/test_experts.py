"""Tests for ExpertRegistry + suggest strategies + skill composition."""

from pathlib import Path

import pytest

from swarm_core.experts import (
    ExpertRegistry,
    ProjectScanStrategy,
    FindingMatchStrategy,
    NullSuggestStrategy,
)
from swarm_core.skills import SkillRegistry


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


# ---------------------------------------------------------------- composition


def _write_skill(p: Path, slug: str, *, universal: bool = False, body: str = "body") -> None:
    p.write_text(
        f"---\nname: {slug.title()}\nslug: {slug}\nwhen_to_use: now\nversion: 1.0.0\n"
        f"universal: {str(universal).lower()}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_composed_prompt_includes_universal_skills(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir / "u.md", "u", universal=True, body="UNIVERSAL_BODY")
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    _write_yaml(experts_dir / "alpha.yaml", "Alpha", body={
        "name": "Alpha", "description": "d", "system_prompt": "ROLE_PROMPT",
    })
    reg = ExpertRegistry(builtin_dir=experts_dir, skill_registry=skill_reg)
    profile = reg.load_profile("alpha")
    composed = profile.composed_system_prompt

    assert "ROLE_PROMPT" in composed
    assert "UNIVERSAL_BODY" in composed
    # Role section comes before universal skill section.
    assert composed.index("ROLE_PROMPT") < composed.index("UNIVERSAL_BODY")


def test_composed_prompt_includes_declared_skills(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir / "u.md", "u", universal=True, body="UNIVERSAL")
    _write_skill(skills_dir / "explicit.md", "explicit", universal=False, body="EXPLICIT_BODY")
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    _write_yaml(experts_dir / "beta.yaml", "Beta", body={
        "name": "Beta", "description": "d",
        "system_prompt": "ROLE",
        "uses_skills": ["explicit"],
    })
    reg = ExpertRegistry(builtin_dir=experts_dir, skill_registry=skill_reg)
    composed = reg.load_profile("beta").composed_system_prompt

    assert "ROLE" in composed
    assert "EXPLICIT_BODY" in composed
    assert "UNIVERSAL" in composed
    # Order: role -> declared -> universal
    assert composed.index("ROLE") < composed.index("EXPLICIT_BODY") < composed.index("UNIVERSAL")


def test_composed_prompt_dedupes_skills(tmp_path: Path):
    """A skill listed in uses_skills AND also universal must not appear twice."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir / "shared.md", "shared", universal=True, body="SHARED_BODY")
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    _write_yaml(experts_dir / "g.yaml", "Gamma", body={
        "name": "Gamma", "description": "d",
        "system_prompt": "ROLE",
        "uses_skills": ["shared"],
    })
    reg = ExpertRegistry(builtin_dir=experts_dir, skill_registry=skill_reg)
    composed = reg.load_profile("g").composed_system_prompt
    assert composed.count("SHARED_BODY") == 1


def test_composed_prompt_skips_unknown_skill(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()  # empty
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    _write_yaml(experts_dir / "d.yaml", "Delta", body={
        "name": "Delta", "description": "d",
        "system_prompt": "ROLE",
        "uses_skills": ["nope"],
    })
    reg = ExpertRegistry(builtin_dir=experts_dir, skill_registry=skill_reg)
    composed = reg.load_profile("d").composed_system_prompt
    # Unknown skill silently skipped; role still present.
    assert "ROLE" in composed


def test_compose_system_prompt_helper_works_on_dict(tmp_path: Path):
    """The dict-based helper must produce the same result as the dataclass path."""
    from swarm_core.experts import compose_system_prompt

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir / "u.md", "u", universal=True, body="UNIVERSAL_BODY")
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    profile_dict = {
        "name": "Test Expert",
        "description": "d",
        "system_prompt": "ROLE_PROMPT_BODY",
    }
    composed = compose_system_prompt(profile_dict, skill_registry=skill_reg)
    assert "ROLE_PROMPT_BODY" in composed
    assert "UNIVERSAL_BODY" in composed
    assert composed.index("ROLE_PROMPT_BODY") < composed.index("UNIVERSAL_BODY")


def test_compose_system_prompt_helper_handles_uses_skills(tmp_path: Path):
    from swarm_core.experts import compose_system_prompt

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir / "u.md", "u", universal=True, body="UNIVERSAL")
    _write_skill(skills_dir / "explicit.md", "explicit", universal=False, body="EXPLICIT")
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    composed = compose_system_prompt(
        {"name": "x", "description": "d", "system_prompt": "ROLE", "uses_skills": ["explicit"]},
        skill_registry=skill_reg,
    )
    assert "ROLE" in composed
    assert "EXPLICIT" in composed
    assert "UNIVERSAL" in composed


def test_composed_prompt_suppresses_inline_solid_dry(tmp_path: Path):
    """Legacy YAMLs with the SOLID+DRY block inlined must not get a duplicate
    via the universal skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir / "solid_dry.md", "solid_dry", universal=True,
                 body="UNIVERSAL_SOLID_DRY")
    skill_reg = SkillRegistry(builtin_dir=skills_dir)

    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    _write_yaml(experts_dir / "legacy.yaml", "Legacy", body={
        "name": "Legacy", "description": "d",
        "system_prompt": (
            "Role checks here.\n\n"
            "## SOLID+DRY enforcement (apply to user code)\n"
            "INLINE_SOLID_DRY content"
        ),
    })
    reg = ExpertRegistry(builtin_dir=experts_dir, skill_registry=skill_reg)
    composed = reg.load_profile("legacy").composed_system_prompt
    assert "INLINE_SOLID_DRY" in composed
    assert "UNIVERSAL_SOLID_DRY" not in composed
