"""Tests for fix_swarm.fix_applier."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fix_swarm.fix_applier import apply_plan, verify_fixes
from fix_swarm.models import FixAction, FixActionType, FixPlan, FixResult


# ── helpers ───────────────────────────────────────────────────────────


def _make_source(tmp_path: Path, name: str = "target.py", content: str | None = None) -> Path:
    """Write a small source file and return its path."""
    src = tmp_path / name
    if content is None:
        content = textwrap.dedent("""\
            import os
            import sys

            def greet(name):
                print("hello " + name)

            def add(a, b):
                return a - b
        """)
    src.write_text(content, encoding="utf-8")
    return src


def _simple_plan(action_type: FixActionType, **overrides) -> FixPlan:
    """Return a one-action FixPlan with sensible defaults."""
    kwargs = dict(
        finding_id="f-1",
        file="target.py",
        line_start=8,
        line_end=8,
        action=action_type,
        old_text="    return a - b\n",
        new_text="    return a + b\n",
        rationale="fix operator",
    )
    kwargs.update(overrides)
    return FixPlan(actions=[FixAction(**kwargs)])


# ── dry-run returns diffs ─────────────────────────────────────────────


class TestDryRun:
    """apply_plan(dry_run=True) should compute diffs but not touch files."""

    def test_dry_run_returns_diff(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        plan = _simple_plan(FixActionType.REPLACE)
        results = apply_plan(plan, base_dir=tmp_path, dry_run=True)
        assert all(r.success for r in results)
        # At least one result should carry a unified diff
        diffs = [r.diff for r in results if r.diff]
        assert len(diffs) == 1
        assert "--- a/target.py" in diffs[0]
        assert "+    return a + b" in diffs[0]

    def test_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        original = src.read_text(encoding="utf-8")
        plan = _simple_plan(FixActionType.REPLACE)
        apply_plan(plan, base_dir=tmp_path, dry_run=True)
        assert src.read_text(encoding="utf-8") == original


# ── backup creates .bak files ────────────────────────────────────────


class TestBackup:
    """apply_plan(backup=True) should create .bak copies before writing."""

    def test_backup_creates_bak_file(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        original = src.read_text(encoding="utf-8")
        plan = _simple_plan(FixActionType.REPLACE)
        apply_plan(plan, base_dir=tmp_path, backup=True)
        bak = tmp_path / "target.py.bak"
        assert bak.is_file()
        assert bak.read_text(encoding="utf-8") == original

    def test_no_backup_when_dry_run(self, tmp_path: Path) -> None:
        _make_source(tmp_path)
        plan = _simple_plan(FixActionType.REPLACE)
        apply_plan(plan, base_dir=tmp_path, dry_run=True, backup=True)
        bak = tmp_path / "target.py.bak"
        assert not bak.exists()


# ── rollback on failure ──────────────────────────────────────────────


class TestRollback:
    """When an action fails, earlier changes to the same file are rolled back."""

    def test_rollback_on_bad_second_action(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        original = src.read_text(encoding="utf-8")
        # Two actions on the same file; the second one targets an invalid line.
        good_action = FixAction(
            finding_id="f-good",
            file="target.py",
            line_start=8,
            line_end=8,
            action=FixActionType.REPLACE,
            old_text="    return a - b\n",
            new_text="    return a + b\n",
            rationale="fix op",
        )
        bad_action = FixAction(
            finding_id="f-bad",
            file="target.py",
            line_start=999,
            line_end=999,
            action=FixActionType.REPLACE,
            old_text="",
            new_text="boom\n",
            rationale="invalid",
        )
        # actions_for_file sorts descending, so bad_action (line 999) runs first
        plan = FixPlan(actions=[good_action, bad_action])
        results = apply_plan(plan, base_dir=tmp_path)
        # The bad action should have failed
        failed = [r for r in results if not r.success]
        assert len(failed) >= 1
        # File must be unchanged because of rollback
        assert src.read_text(encoding="utf-8") == original


# ── verify_fixes ─────────────────────────────────────────────────────


class TestVerifyFixes:
    """verify_fixes checks whether the expected text is present after a fix."""

    def test_verify_after_successful_apply(self, tmp_path: Path) -> None:
        _make_source(tmp_path)
        plan = _simple_plan(FixActionType.REPLACE)
        apply_plan(plan, base_dir=tmp_path)
        results = verify_fixes(plan, base_dir=tmp_path)
        assert all(r.success for r in results)

    def test_verify_fails_when_not_applied(self, tmp_path: Path) -> None:
        _make_source(tmp_path)
        plan = _simple_plan(FixActionType.REPLACE)
        # Do NOT apply -- just verify
        results = verify_fixes(plan, base_dir=tmp_path)
        assert any(not r.success for r in results)

    def test_verify_delete_action(self, tmp_path: Path) -> None:
        _make_source(tmp_path)
        plan = _simple_plan(
            FixActionType.DELETE,
            old_text="    return a - b\n",
            new_text="",
        )
        apply_plan(plan, base_dir=tmp_path)
        results = verify_fixes(plan, base_dir=tmp_path)
        assert all(r.success for r in results)

    def test_verify_missing_file(self, tmp_path: Path) -> None:
        plan = _simple_plan(FixActionType.REPLACE, file="no_such_file.py")
        results = verify_fixes(plan, base_dir=tmp_path)
        assert len(results) == 1
        assert not results[0].success
        assert "not found" in results[0].error.lower()


# ── atomic write (no partial files) ──────────────────────────────────


class TestAtomicWrite:
    """apply_plan should use atomic write so partial content never appears."""

    def test_file_fully_written_or_untouched(self, tmp_path: Path) -> None:
        src = _make_source(tmp_path)
        plan = _simple_plan(FixActionType.REPLACE)
        apply_plan(plan, base_dir=tmp_path)
        content = src.read_text(encoding="utf-8")
        # The fix should be applied completely
        assert "return a + b" in content
        # The old text should be gone
        assert "return a - b" not in content

    def test_no_leftover_tmp_files_on_success(self, tmp_path: Path) -> None:
        _make_source(tmp_path)
        plan = _simple_plan(FixActionType.REPLACE)
        apply_plan(plan, base_dir=tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# ── encoding error handling ──────────────────────────────────────────


class TestEncodingErrors:
    """Gracefully handle files that cannot be decoded as UTF-8."""

    def test_binary_file_returns_error(self, tmp_path: Path) -> None:
        src = tmp_path / "target.py"
        src.write_bytes(b"\x80\x81\x82\x83\xff\xfe")
        plan = _simple_plan(FixActionType.REPLACE)
        results = apply_plan(plan, base_dir=tmp_path)
        assert len(results) == 1
        assert not results[0].success
        assert results[0].error  # should contain a decode error message

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        plan = _simple_plan(FixActionType.REPLACE, file="nonexistent.py")
        results = apply_plan(plan, base_dir=tmp_path)
        assert len(results) == 1
        assert not results[0].success
        assert "not found" in results[0].error.lower()


# ── off-by-one boundary checks ──────────────────────────────────────


class TestBoundaryChecks:
    """Ensure the off-by-one fix for start == len(lines) works correctly."""

    def test_replace_at_last_line(self, tmp_path: Path) -> None:
        """REPLACE on the very last line should succeed."""
        src = _make_source(tmp_path, content="line1\nline2\nline3\n")
        plan = _simple_plan(
            FixActionType.REPLACE,
            line_start=3,
            line_end=3,
            old_text="line3\n",
            new_text="replaced\n",
        )
        results = apply_plan(plan, base_dir=tmp_path)
        assert all(r.success for r in results)
        assert "replaced" in src.read_text(encoding="utf-8")

    def test_replace_past_end_fails(self, tmp_path: Path) -> None:
        """REPLACE with line_start past the last line should fail."""
        _make_source(tmp_path, content="line1\nline2\n")
        plan = _simple_plan(
            FixActionType.REPLACE,
            line_start=3,
            line_end=3,
            old_text="",
            new_text="nope\n",
        )
        results = apply_plan(plan, base_dir=tmp_path)
        assert len(results) == 1
        assert not results[0].success
        assert "past end" in results[0].error.lower()

    def test_insert_at_end_appends(self, tmp_path: Path) -> None:
        """INSERT with start == len(lines) should append at end."""
        _make_source(tmp_path, content="line1\nline2\n")
        plan = _simple_plan(
            FixActionType.INSERT,
            line_start=3,
            line_end=3,
            old_text="",
            new_text="line3\n",
        )
        results = apply_plan(plan, base_dir=tmp_path)
        assert all(r.success for r in results)
        content = src_path(tmp_path).read_text(encoding="utf-8")
        assert content.endswith("line3\n")

    def test_delete_past_end_fails(self, tmp_path: Path) -> None:
        """DELETE with start past the last line should fail."""
        _make_source(tmp_path, content="line1\nline2\n")
        plan = _simple_plan(
            FixActionType.DELETE,
            line_start=3,
            line_end=3,
            old_text="",
            new_text="",
        )
        results = apply_plan(plan, base_dir=tmp_path)
        assert len(results) == 1
        assert not results[0].success
        assert "past end" in results[0].error.lower()


def src_path(tmp_path: Path) -> Path:
    """Return the target.py path within the temp dir."""
    return tmp_path / "target.py"
