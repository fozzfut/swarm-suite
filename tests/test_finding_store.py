"""Tests for FindingStore -- JSONL persistence with filtering and limits."""

import json

import pytest

from review_swarm.finding_store import FindingStore
from review_swarm.models import (
    Category,
    Finding,
    Severity,
    Status,
)


def _make_finding(**overrides) -> Finding:
    """Create a Finding with reasonable defaults, accepting overrides."""
    defaults = {
        "id": Finding.generate_id(),
        "session_id": "sess-test-001",
        "expert_role": "thread-safety",
        "agent_id": "agent-001",
        "file": "src/main.py",
        "line_start": 10,
        "line_end": 20,
        "snippet": "x = shared_state",
        "severity": Severity.MEDIUM,
        "category": Category.BUG,
        "title": "Unprotected shared state",
        "confidence": 0.7,
    }
    defaults.update(overrides)
    return Finding(**defaults)


class TestFindingStorePostAndGet:
    def test_post_and_get(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        finding = _make_finding()
        returned_id = store.post(finding)

        assert returned_id == finding.id
        results = store.get()
        assert len(results) == 1
        assert results[0].id == finding.id
        assert results[0].created_at != ""
        assert results[0].updated_at != ""


class TestFindingStoreFilters:
    def test_filter_by_severity(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding(severity=Severity.HIGH))
        store.post(_make_finding(severity=Severity.LOW))
        store.post(_make_finding(severity=Severity.HIGH))

        highs = store.get(severity=Severity.HIGH)
        lows = store.get(severity=Severity.LOW)
        assert len(highs) == 2
        assert len(lows) == 1

    def test_filter_by_file(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding(file="src/main.py"))
        store.post(_make_finding(file="src/utils.py"))
        store.post(_make_finding(file="src/main.py"))

        main_findings = store.get(file="src/main.py")
        utils_findings = store.get(file="src/utils.py")
        assert len(main_findings) == 2
        assert len(utils_findings) == 1

    def test_filter_by_category(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding(category=Category.BUG))
        store.post(_make_finding(category=Category.SECURITY))
        store.post(_make_finding(category=Category.BUG))

        bugs = store.get(category=Category.BUG)
        security = store.get(category=Category.SECURITY)
        assert len(bugs) == 2
        assert len(security) == 1

    def test_filter_by_status(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding())
        store.post(_make_finding())

        open_findings = store.get(status=Status.OPEN)
        confirmed_findings = store.get(status=Status.CONFIRMED)
        assert len(open_findings) == 2
        assert len(confirmed_findings) == 0

    def test_filter_by_expert_role(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding(expert_role="thread-safety"))
        store.post(_make_finding(expert_role="security"))
        store.post(_make_finding(expert_role="thread-safety"))

        thread_findings = store.get(expert_role="thread-safety")
        security_findings = store.get(expert_role="security")
        assert len(thread_findings) == 2
        assert len(security_findings) == 1

    def test_filter_by_min_confidence(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding(confidence=0.3))
        store.post(_make_finding(confidence=0.8))
        store.post(_make_finding(confidence=0.95))

        above_07 = store.get(min_confidence=0.7)
        assert len(above_07) == 2
        above_09 = store.get(min_confidence=0.9)
        assert len(above_09) == 1


class TestFindingStorePersistence:
    def test_persistence_across_instances(self, tmp_path):
        jsonl_path = tmp_path / "findings.jsonl"
        store1 = FindingStore(jsonl_path)
        f1 = _make_finding(title="First finding")
        f2 = _make_finding(title="Second finding")
        store1.post(f1)
        store1.post(f2)

        # New instance should load the same data
        store2 = FindingStore(jsonl_path)
        assert store2.count() == 2
        result = store2.get_by_id(f1.id)
        assert result is not None
        assert result.title == "First finding"


class TestFindingStoreGetById:
    def test_get_by_id(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        finding = _make_finding()
        store.post(finding)

        result = store.get_by_id(finding.id)
        assert result is not None
        assert result.id == finding.id
        assert result.title == finding.title

    def test_get_by_id_not_found(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        result = store.get_by_id("f-nonexistent")
        assert result is None


class TestFindingStoreUpdateStatus:
    def test_update_status(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        finding = _make_finding()
        store.post(finding)

        store.update_status(finding.id, Status.CONFIRMED)
        result = store.get_by_id(finding.id)
        assert result is not None
        assert result.status == Status.CONFIRMED


class TestFindingStoreLimit:
    def test_finding_limit(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl", max_findings=3)
        store.post(_make_finding())
        store.post(_make_finding())
        store.post(_make_finding())

        with pytest.raises(ValueError, match="limit"):
            store.post(_make_finding())

        assert store.count() == 3


class TestFindingStoreReactions:
    def test_add_reaction_to_finding(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        finding = _make_finding()
        store.post(finding)

        reaction_dict = {
            "agent_id": "agent-002",
            "expert_role": "security",
            "reaction": "confirm",
            "reason": "Verified the race condition",
        }
        store.add_reaction(finding.id, reaction_dict)

        result = store.get_by_id(finding.id)
        assert result is not None
        assert len(result.reactions) == 1
        assert result.reactions[0]["reason"] == "Verified the race condition"


class TestFindingStoreRelatedFindings:
    def test_update_related_findings(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        f1 = _make_finding()
        f2 = _make_finding()
        store.post(f1)
        store.post(f2)

        store.add_related(f1.id, f2.id)

        result1 = store.get_by_id(f1.id)
        assert result1 is not None
        assert f2.id in result1.related_findings

        # Adding the same related_id again should not duplicate
        store.add_related(f1.id, f2.id)
        result1_again = store.get_by_id(f1.id)
        assert result1_again is not None
        assert result1_again.related_findings.count(f2.id) == 1


class TestFindingStoreCounts:
    def test_count(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        assert store.count() == 0
        store.post(_make_finding())
        store.post(_make_finding())
        assert store.count() == 2

    def test_count_by_severity(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        store.post(_make_finding(severity=Severity.HIGH))
        store.post(_make_finding(severity=Severity.HIGH))
        store.post(_make_finding(severity=Severity.LOW))

        counts = store.count_by_severity()
        assert counts["high"] == 2
        assert counts["low"] == 1

    def test_count_by_status(self, tmp_path):
        store = FindingStore(tmp_path / "findings.jsonl")
        f1 = _make_finding()
        f2 = _make_finding()
        store.post(f1)
        store.post(f2)
        store.update_status(f1.id, Status.CONFIRMED)

        counts = store.count_by_status()
        assert counts["open"] == 1
        assert counts["confirmed"] == 1


class TestFindingStoreAtomicWrite:
    """Test that _flush() uses atomic write (temp file + os.replace)."""

    def test_atomic_flush_produces_valid_jsonl(self, tmp_path):
        """After an atomic flush, the JSONL file exists and contains valid JSON lines."""
        jsonl_path = tmp_path / "findings.jsonl"
        store = FindingStore(jsonl_path)
        f1 = _make_finding(title="First")
        f2 = _make_finding(title="Second")
        store.post(f1)
        store.post(f2)

        # Trigger a flush via update_status (which calls _flush internally)
        store.update_status(f1.id, Status.CONFIRMED)

        # File must exist and contain valid JSONL
        assert jsonl_path.exists()
        text = jsonl_path.read_text(encoding="utf-8")
        lines = [line for line in text.strip().split("\n") if line.strip()]
        assert len(lines) == 2

        # Each line must be valid JSON with expected keys
        for line in lines:
            data = json.loads(line)
            assert "id" in data
            assert "title" in data

    def test_atomic_flush_no_temp_files_left(self, tmp_path):
        """After a successful flush, no .tmp files remain in the directory."""
        jsonl_path = tmp_path / "findings.jsonl"
        store = FindingStore(jsonl_path)
        store.post(_make_finding())
        store.update_status(list(store._findings.keys())[0], Status.CONFIRMED)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover temp files: {tmp_files}"

    def test_atomic_flush_preserves_data_after_reload(self, tmp_path):
        """Data written by atomic flush can be reloaded by a new store instance."""
        jsonl_path = tmp_path / "findings.jsonl"
        store1 = FindingStore(jsonl_path)
        f1 = _make_finding(title="Atomic test finding")
        store1.post(f1)
        store1.update_status(f1.id, Status.CONFIRMED)

        # Reload from disk
        store2 = FindingStore(jsonl_path)
        assert store2.count() == 1
        reloaded = store2.get_by_id(f1.id)
        assert reloaded is not None
        assert reloaded.title == "Atomic test finding"
        assert reloaded.status == Status.CONFIRMED
