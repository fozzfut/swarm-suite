"""Tests for swarm_core.skills."""

from pathlib import Path

import pytest

from swarm_core.skills import Skill, SkillRegistry


def _write(p: Path, body: str) -> Path:
    p.write_text(body, encoding="utf-8")
    return p


def test_load_built_in_skills():
    """Built-in skills load and parse cleanly."""
    reg = SkillRegistry()
    slugs = {s.slug for s in reg.list_skills()}
    # Five skills shipped by swarm-suite (3 ported + 2 originals).
    expected = {"systematic_debugging", "brainstorming", "writing_plans",
                "self_review", "solid_dry", "karpathy_guidelines"}
    assert expected.issubset(slugs), f"missing: {expected - slugs}"


def test_universal_flag_visible():
    reg = SkillRegistry()
    universal_slugs = {s.slug for s in reg.universal_skills()}
    assert "solid_dry" in universal_slugs
    assert "karpathy_guidelines" in universal_slugs


def test_get_unknown_raises(tmp_path: Path):
    reg = SkillRegistry(builtin_dir=tmp_path)  # empty dir
    with pytest.raises(FileNotFoundError):
        reg.get("does_not_exist")


def test_skill_compose_body_announces(tmp_path: Path):
    _write(tmp_path / "demo.md",
           "---\nname: Demo\nslug: demo\nwhen_to_use: when testing\nversion: 0.1.0\n---\n\nbody text\n")
    reg = SkillRegistry(builtin_dir=tmp_path)
    skill = reg.get("demo")
    composed = skill.compose_body()
    assert "Active skill: **Demo**" in composed
    assert "body text" in composed


def test_attribution_appended(tmp_path: Path):
    _write(tmp_path / "x.md",
           "---\nname: X\nslug: x\nwhen_to_use: now\nversion: 1.0.0\n"
           'attribution: "Adapted from somewhere"\n---\n\nbody\n')
    reg = SkillRegistry(builtin_dir=tmp_path)
    composed = reg.get("x").compose_body()
    assert "Adapted from somewhere" in composed


def test_corrupt_frontmatter_skipped(tmp_path: Path, caplog):
    _write(tmp_path / "good.md",
           "---\nname: Good\nslug: good\nwhen_to_use: w\nversion: 1.0.0\n---\nbody\n")
    _write(tmp_path / "bad.md", "no frontmatter here\njust text\n")
    reg = SkillRegistry(builtin_dir=tmp_path)
    slugs = {s.slug for s in reg.list_skills()}
    assert slugs == {"good"}


def test_missing_required_field_skipped(tmp_path: Path):
    # Missing `version`
    _write(tmp_path / "incomplete.md",
           "---\nname: I\nslug: incomplete\nwhen_to_use: now\n---\nbody\n")
    reg = SkillRegistry(builtin_dir=tmp_path)
    assert reg.list_skills() == []


def test_format_doc_not_loaded(tmp_path: Path):
    """SKILL_FORMAT.md is the spec, not a skill itself."""
    reg = SkillRegistry()
    slugs = {s.slug for s in reg.list_skills()}
    assert "SKILL_FORMAT" not in slugs


def test_custom_dir_overrides_builtin(tmp_path: Path):
    builtin = tmp_path / "builtin"
    custom = tmp_path / "custom"
    builtin.mkdir()
    custom.mkdir()
    _write(builtin / "x.md",
           "---\nname: X-builtin\nslug: x\nwhen_to_use: w\nversion: 1.0.0\n---\nbody1\n")
    _write(custom / "x.md",
           "---\nname: X-custom\nslug: x\nwhen_to_use: w\nversion: 2.0.0\n---\nbody2\n")
    reg = SkillRegistry(builtin_dir=builtin, custom_dirs=[custom])
    skill = reg.get("x")
    assert skill.name == "X-custom"
    assert skill.version == "2.0.0"
