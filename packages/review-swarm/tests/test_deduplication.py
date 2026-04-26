"""Tests for FindingStore duplicate detection."""

from review_swarm.finding_store import FindingStore
from review_swarm.models import Finding, Severity, Category


def _make_finding(**overrides) -> Finding:
    defaults = {
        "id": Finding.generate_id(),
        "session_id": "sess-test",
        "expert_role": "thread-safety",
        "agent_id": "agent-001",
        "file": "src/main.py",
        "line_start": 10,
        "line_end": 20,
        "title": "Race condition in handler",
        "severity": Severity.HIGH,
        "category": Category.BUG,
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return Finding(**defaults)


class TestFindDuplicates:
    def test_exact_duplicate(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        f1 = _make_finding(title="Race condition in handler")
        store.post(f1)

        dupes = store.find_duplicates(
            "src/main.py", 10, 20, "Race condition in handler", exclude_id="",
        )
        assert len(dupes) == 1
        assert dupes[0].id == f1.id

    def test_overlapping_lines_similar_title(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        f1 = _make_finding(line_start=10, line_end=20, title="Race condition in handler")
        store.post(f1)

        dupes = store.find_duplicates(
            "src/main.py", 15, 25, "Race condition in cache handler",
        )
        assert len(dupes) == 1

    def test_no_line_overlap(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        f1 = _make_finding(line_start=10, line_end=20, title="Race condition")
        store.post(f1)

        dupes = store.find_duplicates("src/main.py", 30, 40, "Race condition")
        assert len(dupes) == 0

    def test_different_file(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        f1 = _make_finding(file="src/main.py", title="Race condition")
        store.post(f1)

        dupes = store.find_duplicates("src/other.py", 10, 20, "Race condition")
        assert len(dupes) == 0

    def test_different_title(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        f1 = _make_finding(title="Race condition in handler")
        store.post(f1)

        dupes = store.find_duplicates("src/main.py", 10, 20, "Missing error handling")
        assert len(dupes) == 0

    def test_exclude_self(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        f1 = _make_finding(title="Race condition")
        store.post(f1)

        dupes = store.find_duplicates(
            "src/main.py", 10, 20, "Race condition", exclude_id=f1.id,
        )
        assert len(dupes) == 0

    def test_multiple_duplicates(self, tmp_path):
        store = FindingStore(tmp_path / "f.jsonl")
        store.post(_make_finding(title="Race condition in handler", expert_role="a"))
        store.post(_make_finding(title="Race condition in handler", expert_role="b"))

        dupes = store.find_duplicates("src/main.py", 10, 20, "Race condition in handler")
        assert len(dupes) == 2
