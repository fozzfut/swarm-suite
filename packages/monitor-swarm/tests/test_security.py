"""Security-focused tests for monitor-swarm — session_id path traversal
guard, ReDoS pattern dropping in expert_profiler.

These tests cover the hardening added in response to the self-review
session (see arch-swarm review of commits 1766343..86747ae)."""

from __future__ import annotations

from pathlib import Path

import pytest

from monitor_swarm.expert_profiler import ExpertProfiler, _is_pattern_safe
from monitor_swarm.server import _validate_session_id


# ─── session_id validator ──────────────────────────────────────────────────


@pytest.mark.parametrize("good", [
    "mon-abc1",
    "abc",
    "X_Y_Z",
    "session-123",
    "a" * 64,
])
def test_validate_session_id_accepts_safe(good: str) -> None:
    assert _validate_session_id(good) is None


@pytest.mark.parametrize("bad", [
    "",                          # empty
    "../etc",                    # path-traversal
    "../../home",                # multi-step traversal
    "abc/def",                   # path separator
    "abc\\def",                  # Windows path separator
    "with space",                # space
    "with.dot",                  # dot
    "a" * 65,                    # too long
    "tab\there",                 # control char
    "weird;injection",           # semicolon
])
def test_validate_session_id_rejects_unsafe(bad: str) -> None:
    err = _validate_session_id(bad)
    assert err is not None
    assert err  # non-empty message


# ─── expert_profiler ReDoS guard ───────────────────────────────────────────


@pytest.mark.parametrize("safe", [
    r"printf\(",
    r"LOG_(DEBUG|INFO)\s*\(",
    r"defmt::println!",
    r"\bISR\b",
])
def test_safe_patterns_accepted(safe: str) -> None:
    assert _is_pattern_safe(safe) is True


@pytest.mark.parametrize("unsafe", [
    r"(a+)+b",                # classic ReDoS
    r"(.*)*x",                # nested star
    r"(\w+)+",                # nested plus on group
    r".+.+.+",                # consecutive greedy
    r".*.*",                  # consecutive star
    "x" * 250,                # too long
    "(unclosed",              # invalid regex
    "",                       # empty
])
def test_unsafe_patterns_rejected(unsafe: str) -> None:
    assert _is_pattern_safe(unsafe) is False


def test_unsafe_yaml_pattern_dropped_at_use_time(tmp_path: Path) -> None:
    """A custom expert YAML with a ReDoS pattern must not crash the suggester;
    the unsafe pattern is logged + dropped, the rest of the YAML stands."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.c").write_text("printf(\"hello\");\n", encoding="utf-8")

    custom_dir = tmp_path / "custom_experts"
    custom_dir.mkdir()
    (custom_dir / "trojan.yaml").write_text(
        "name: Trojan Expert\n"
        "description: Has a malicious ReDoS pattern\n"
        "file_patterns: ['**/*.c']\n"
        "relevance_signals:\n"
        "  imports: [stdio]\n"
        "  patterns:\n"
        "    - '(a+)+b'\n"        # ReDoS — must be dropped
        "    - 'printf'\n"        # safe — must be kept
        "system_prompt: 'placeholder'\n"
        "uses_skills: []\n",
        encoding="utf-8",
    )

    profiler = ExpertProfiler(custom_dirs=[custom_dir])
    # Suggester completes promptly (no hang). The trojan expert is loaded but
    # its ReDoS pattern is filtered out before re.search is ever invoked.
    ranked = profiler.suggest_experts(tmp_path)
    by_slug = {r["slug"]: r for r in ranked}
    assert "trojan" in by_slug
    # The 'printf' signal still matched (so signal_hits > 0); the ReDoS
    # pattern was dropped without executing.
    assert by_slug["trojan"]["signal_hits"] > 0
