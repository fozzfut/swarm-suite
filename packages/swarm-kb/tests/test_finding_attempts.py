"""Tests for the per-finding circuit breaker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.finding_attempts import (
    FindingAttemptCounter,
    MAX_ATTEMPTS_PER_FINDING,
    ESCALATED_STATUS,
)


def test_increment_increases_count(tmp_path: Path):
    c = FindingAttemptCounter(tmp_path)
    assert c.get("f-1") == 0
    assert c.increment("f-1") == 1
    assert c.increment("f-1") == 2
    assert c.get("f-1") == 2


def test_should_escalate_at_threshold(tmp_path: Path):
    c = FindingAttemptCounter(tmp_path)
    for _ in range(MAX_ATTEMPTS_PER_FINDING - 1):
        c.increment("f-1")
    assert not c.should_escalate("f-1")
    c.increment("f-1")
    assert c.should_escalate("f-1")


def test_reset_clears_counter(tmp_path: Path):
    c = FindingAttemptCounter(tmp_path)
    c.increment("f-1")
    c.increment("f-1")
    c.reset("f-1")
    assert c.get("f-1") == 0


def test_persists_across_instances(tmp_path: Path):
    c1 = FindingAttemptCounter(tmp_path)
    c1.increment("f-1")
    c1.increment("f-1")
    c2 = FindingAttemptCounter(tmp_path)
    assert c2.get("f-1") == 2
    assert ESCALATED_STATUS == "arch_review_needed"


def test_corrupt_file_silently_recovers(tmp_path: Path):
    c = FindingAttemptCounter(tmp_path)
    c.increment("f-1")
    # Corrupt the file
    (tmp_path / "fix_attempts.json").write_text("not json", encoding="utf-8")
    # Next read returns empty (recoverable, not crash)
    assert c.get("f-1") == 0
