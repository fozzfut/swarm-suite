"""Tests for the legacy -> per-project migration (Phase 5 M4)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

# Allow swarm-kb to be imported without an editable install (matches the
# pattern used elsewhere in this repo for cross-package testing).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.cli import main as cli_main
from swarm_kb.config import SuiteConfig
from swarm_kb.migrate_per_project import (
    LEGACY_UNATTRIBUTED_LABEL,
    cleanup_legacy,
    run_migration,
)
from swarm_kb.paths import project_hash_for


# ---------------------------------------------------------------------------
# Fixtures: build a synthetic legacy KB on disk
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> SuiteConfig:
    return SuiteConfig(storage_root=str(tmp_path / "swarm-kb"))


def _seed_session(
    config: SuiteConfig, tool: str, sid: str, *, project_path: str | None,
) -> Path:
    sdir = config.tool_sessions_path(tool) / sid
    sdir.mkdir(parents=True, exist_ok=True)
    meta: dict = {"session_id": sid, "tool": tool}
    if project_path is not None:
        meta["project_path"] = project_path
    (sdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # A second file to ensure the directory tree moves intact.
    (sdir / "findings.jsonl").write_text(
        json.dumps({"id": f"{sid}-finding-1"}) + "\n",
        encoding="utf-8",
    )
    return sdir


def _seed_decisions(config: SuiteConfig, entries: list[dict]) -> Path:
    path = config.decisions_path / "decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return path


def _seed_debate_dir(
    config: SuiteConfig, debate_id: str, project_path: str,
) -> Path:
    ddir = config.debates_path / "active" / debate_id
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "debate.json").write_text(
        json.dumps({"id": debate_id, "project_path": project_path}, indent=2),
        encoding="utf-8",
    )
    return ddir


def _seed_pipeline(
    config: SuiteConfig, pid: str, project_path: str,
) -> Path:
    config.pipelines_path.mkdir(parents=True, exist_ok=True)
    p = config.pipelines_path / f"{pid}.json"
    p.write_text(
        json.dumps({"id": pid, "project_path": project_path}, indent=2),
        encoding="utf-8",
    )
    return p


def _seed_code_map(config: SuiteConfig, project_path: str) -> tuple[str, Path]:
    project_hash = project_hash_for(project_path)
    cm = config.code_map_path / project_hash
    cm.mkdir(parents=True, exist_ok=True)
    (cm / "files.json").write_text("[]", encoding="utf-8")
    return project_hash, cm


def _seed_vector_index(config: SuiteConfig) -> Path:
    p = config.vector_index_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"sqlite-stub")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basic_session_move(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_session(config, "review", "sess-A1", project_path=project_a)

    result = run_migration(config)

    assert result.sessions_migrated == 1
    project_hash = project_hash_for(project_a)
    expected = config.project_tool_sessions_path(project_a, "review") / "sess-A1"
    assert expected.exists()
    assert (expected / "findings.jsonl").exists()
    # Legacy should have been moved (default keep_legacy=False)
    assert not (config.tool_sessions_path("review") / "sess-A1").exists()
    # Project meta written
    meta = json.loads(
        (config.projects_root / project_hash / "meta.json").read_text(encoding="utf-8"),
    )
    assert meta["migrated_from_legacy"] is True
    assert meta["project_path"] == str(Path(project_a).resolve())


def test_keep_legacy_copies_instead_of_moving(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_session(config, "fix", "sess-K1", project_path=project_a)

    result = run_migration(config, keep_legacy=True)

    assert result.sessions_migrated == 1
    target = config.project_tool_sessions_path(project_a, "fix") / "sess-K1"
    assert target.exists()
    # Legacy untouched
    assert (config.tool_sessions_path("fix") / "sess-K1").exists()


def test_dry_run_does_not_move_anything(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    legacy = _seed_session(config, "review", "sess-D1", project_path=project_a)
    decisions_path = _seed_decisions(config, [
        {"id": "adr-1", "project_path": project_a, "title": "T1"},
    ])

    result = run_migration(config, dry_run=True)

    # Counters still reflect what *would* happen, but nothing on disk.
    assert result.sessions_migrated == 1
    assert result.decisions_migrated == 1
    assert legacy.exists()
    assert decisions_path.exists()
    # No project root should have been created.
    project_hash = project_hash_for(project_a)
    assert not (config.projects_root / project_hash).exists()


def test_default_project_bucket_for_unattributed_session(tmp_path: Path):
    config = _make_config(tmp_path)
    default_proj = str(tmp_path / "default-proj")
    Path(default_proj).mkdir()
    # Session with no project_path field.
    _seed_session(config, "doc", "sess-U1", project_path=None)

    result = run_migration(config, default_project=default_proj)

    assert result.sessions_migrated == 1
    target = config.project_tool_sessions_path(default_proj, "doc") / "sess-U1"
    assert target.exists()


def test_unattributed_falls_back_to_legacy_bucket(tmp_path: Path):
    config = _make_config(tmp_path)
    _seed_session(config, "arch", "sess-U2", project_path=None)

    result = run_migration(config)

    assert result.sessions_migrated == 1
    legacy_hash = project_hash_for(LEGACY_UNATTRIBUTED_LABEL)
    target = config.projects_root / legacy_hash / "arch" / "sessions" / "sess-U2"
    assert target.exists()


def test_decisions_split_by_project_path(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    project_b = str(tmp_path / "proj-b")
    for p in (project_a, project_b):
        Path(p).mkdir()

    _seed_decisions(config, [
        {"id": "adr-1", "project_path": project_a, "title": "A1"},
        {"id": "adr-2", "project_path": project_b, "title": "B1"},
        {"id": "adr-3", "project_path": project_a, "title": "A2"},
    ])

    result = run_migration(config)

    assert result.decisions_migrated == 3
    a_lines = (config.project_decisions_path(project_a) / "decisions.jsonl") \
        .read_text(encoding="utf-8").strip().splitlines()
    b_lines = (config.project_decisions_path(project_b) / "decisions.jsonl") \
        .read_text(encoding="utf-8").strip().splitlines()
    assert len(a_lines) == 2
    assert len(b_lines) == 1
    a_ids = {json.loads(line)["id"] for line in a_lines}
    assert a_ids == {"adr-1", "adr-3"}


def test_idempotent_rerun_does_not_duplicate(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_session(config, "review", "sess-I1", project_path=project_a)
    _seed_decisions(config, [
        {"id": "adr-X", "project_path": project_a, "title": "X"},
    ])

    first = run_migration(config, keep_legacy=True)
    assert first.sessions_migrated == 1
    assert first.decisions_migrated == 1

    # Second run -- decisions already merged by id; sessions already
    # at target (skipped via target.exists() guard).
    second = run_migration(config, keep_legacy=True)
    assert second.sessions_migrated == 0
    assert second.decisions_migrated == 0
    # Target decisions file still has only one line.
    lines = (config.project_decisions_path(project_a) / "decisions.jsonl") \
        .read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_debate_dirs_migrated(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_debate_dir(config, "dbt-1", project_a)

    result = run_migration(config)
    assert result.debate_dirs_migrated == 1
    target = config.project_debates_path(project_a) / "active" / "dbt-1"
    assert target.exists()
    assert (target / "debate.json").exists()


def test_pipelines_migrated(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_pipeline(config, "pipe-aaaa", project_a)

    result = run_migration(config)
    assert result.pipelines_migrated == 1
    target = config.project_pipelines_path(project_a) / "pipe-aaaa.json"
    assert target.exists()


def test_code_map_moved_under_project_root(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    project_hash, legacy_cm = _seed_code_map(config, project_a)

    result = run_migration(config)

    assert result.code_maps_migrated == 1
    new_cm = config.projects_root / project_hash / "code-map"
    assert new_cm.exists()
    assert (new_cm / "files.json").exists()
    assert not legacy_cm.exists()


def test_legacy_vector_index_dropped(tmp_path: Path):
    config = _make_config(tmp_path)
    legacy = _seed_vector_index(config)
    assert legacy.exists()

    result = run_migration(config)

    assert result.vector_index_dropped is True
    assert not legacy.exists()


def test_legacy_vector_index_renamed_with_keep_legacy(tmp_path: Path):
    config = _make_config(tmp_path)
    legacy = _seed_vector_index(config)

    result = run_migration(config, keep_legacy=True)

    assert result.vector_index_dropped is True
    assert not legacy.exists()
    backup = legacy.with_suffix(legacy.suffix + ".bak")
    assert backup.exists()


def test_cleanup_legacy_finalize(tmp_path: Path):
    config = _make_config(tmp_path)
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_session(config, "review", "sess-F1", project_path=project_a)
    _seed_decisions(config, [
        {"id": "adr-F", "project_path": project_a, "title": "F"},
    ])
    _seed_vector_index(config)

    # Use keep-legacy first so the legacy paths still exist for finalize.
    run_migration(config, keep_legacy=True)
    deleted = cleanup_legacy(config)

    # Decisions, debates, pipelines, code-map, index, plus per-tool dirs.
    assert any(p.name == "decisions" for p in deleted)
    assert any(p.name == "review" for p in deleted)
    # And nothing remains on disk for those.
    assert not config.decisions_path.exists()
    assert not config.tool_sessions_path("review").parent.exists()


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


def _set_kb_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Force SuiteConfig.load to use a tmp_path-backed config.yaml."""
    kb_root = tmp_path / "swarm-kb"
    kb_root.mkdir(parents=True, exist_ok=True)
    cfg_yaml = kb_root / "config.yaml"
    cfg_yaml.write_text(f"storage_root: {kb_root}\n", encoding="utf-8")

    # Patch _DEFAULT_ROOT lookup by patching SuiteConfig.load to load from
    # our config file.
    import swarm_kb.config as cfg_mod

    original_load = cfg_mod.SuiteConfig.load

    def patched_load(cls, path=None):
        return original_load.__func__(cls, cfg_yaml)

    monkeypatch.setattr(
        cfg_mod.SuiteConfig, "load", classmethod(patched_load),
    )


def test_cli_dry_run_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _set_kb_root(monkeypatch, tmp_path)
    config = SuiteConfig.load()
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_session(config, "review", "sess-CLI-1", project_path=project_a)

    runner = CliRunner()
    res = runner.invoke(cli_main, ["migrate-to-per-project", "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "[dry-run]" in res.output
    assert "Migration summary:" in res.output
    # Legacy session still exists since this is dry-run.
    assert (config.tool_sessions_path("review") / "sess-CLI-1").exists()


def test_cli_real_run_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _set_kb_root(monkeypatch, tmp_path)
    config = SuiteConfig.load()
    project_a = str(tmp_path / "proj-a")
    Path(project_a).mkdir()
    _seed_session(config, "review", "sess-CLI-2", project_path=project_a)

    runner = CliRunner()
    res = runner.invoke(cli_main, ["migrate-to-per-project"])
    assert res.exit_code == 0, res.output
    assert "Migration summary:" in res.output
    assert "Next steps:" in res.output
    target = config.project_tool_sessions_path(project_a, "review") / "sess-CLI-2"
    assert target.exists()
