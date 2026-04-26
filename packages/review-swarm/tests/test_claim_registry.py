"""Tests for ClaimRegistry -- file claim tracking with TTL expiry."""

from datetime import datetime, timedelta, timezone

from review_swarm.claim_registry import ClaimRegistry
from review_swarm.models import Claim, ClaimStatus


class TestClaimAndGet:
    def test_claim_and_get(self, tmp_path):
        reg = ClaimRegistry(tmp_path / "claims.json")
        claim = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")

        assert claim.session_id == "sess-1"
        assert claim.file == "src/main.py"
        assert claim.expert_role == "thread-safety"
        assert claim.agent_id == "agent-001"
        assert claim.status == ClaimStatus.ACTIVE

        claims = reg.get_claims("sess-1")
        assert len(claims) == 1
        assert claims[0].id == claim.id


class TestClaimAlreadyClaimed:
    def test_claim_already_claimed_by_same(self, tmp_path):
        """Same agent re-claiming gets the same claim back (same id)."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        first = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")
        second = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")

        assert second.id == first.id
        assert second.agent_id == "agent-001"

    def test_different_experts_get_independent_claims(self, tmp_path):
        """Different experts can claim the same file independently."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        first = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")
        second = reg.claim("sess-1", "src/main.py", "security", "agent-002")

        assert second.id != first.id  # Independent claims
        assert second.expert_role == "security"
        assert second.agent_id == "agent-002"

        claims = reg.get_claims("sess-1")
        assert len(claims) == 2

    def test_same_expert_same_file_returns_existing(self, tmp_path):
        """Same expert re-claiming same file gets the existing claim back."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        first = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")
        second = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-002")

        assert second.id == first.id  # Same claim returned


class TestRelease:
    def test_release(self, tmp_path):
        reg = ClaimRegistry(tmp_path / "claims.json")
        reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")

        reg.release("sess-1", "src/main.py", "thread-safety")

        claims = reg.get_claims("sess-1")
        assert len(claims) == 0

    def test_release_nonexistent_is_noop(self, tmp_path):
        """Releasing a claim that doesn't exist should not raise."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        reg.release("sess-1", "src/nonexistent.py", "thread-safety")
        # No exception expected


class TestExpiry:
    def test_expired_claims_filtered(self, tmp_path):
        """Claims with old timestamp + short TTL are filtered from get_claims."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        claim = reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")

        # Manually backdate the claim so it appears expired
        old_time = datetime.now(timezone.utc) - timedelta(seconds=3600)
        claim.claimed_at = old_time.isoformat()
        claim.ttl_seconds = 1  # 1 second TTL, already 3600s old
        reg._save()

        claims = reg.get_claims("sess-1")
        assert len(claims) == 0


class TestPersistence:
    def test_persistence(self, tmp_path):
        """Claims survive across ClaimRegistry instances."""
        json_path = tmp_path / "claims.json"
        reg1 = ClaimRegistry(json_path)
        claim = reg1.claim("sess-1", "src/main.py", "thread-safety", "agent-001")

        # New instance loads from same file
        reg2 = ClaimRegistry(json_path)
        claims = reg2.get_claims("sess-1")
        assert len(claims) == 1
        assert claims[0].id == claim.id
        assert claims[0].file == "src/main.py"


class TestSessionFiltering:
    def test_get_claims_filters_by_session(self, tmp_path):
        """Claims in different sessions only show for their session."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")
        reg.claim("sess-2", "src/utils.py", "security", "agent-002")

        sess1_claims = reg.get_claims("sess-1")
        sess2_claims = reg.get_claims("sess-2")
        assert len(sess1_claims) == 1
        assert sess1_claims[0].file == "src/main.py"
        assert len(sess2_claims) == 1
        assert sess2_claims[0].file == "src/utils.py"


class TestReleaseAll:
    def test_release_all_for_session(self, tmp_path):
        """release_all releases only the specified session's claims."""
        reg = ClaimRegistry(tmp_path / "claims.json")
        reg.claim("sess-1", "src/main.py", "thread-safety", "agent-001")
        reg.claim("sess-1", "src/utils.py", "security", "agent-001")
        reg.claim("sess-2", "src/other.py", "performance", "agent-002")

        reg.release_all("sess-1")

        assert len(reg.get_claims("sess-1")) == 0
        assert len(reg.get_claims("sess-2")) == 1
