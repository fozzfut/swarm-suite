"""Tests for RateLimiter -- per-agent sliding window rate limiting."""

import time

import pytest

from review_swarm.rate_limiter import RateLimiter


class TestRateLimiterCheck:
    def test_allows_calls_within_limit(self):
        """Calls within max_calls should succeed."""
        limiter = RateLimiter(max_calls=5, window_seconds=60)
        for _ in range(5):
            limiter.check("agent-a")  # should not raise

    def test_exceeds_limit_raises(self):
        """Call beyond max_calls should raise ValueError."""
        limiter = RateLimiter(max_calls=3, window_seconds=60)
        limiter.check("agent-a")
        limiter.check("agent-a")
        limiter.check("agent-a")
        with pytest.raises(ValueError, match="Rate limit exceeded for agent-a"):
            limiter.check("agent-a")

    def test_different_agents_independent(self):
        """Each agent has its own counter."""
        limiter = RateLimiter(max_calls=2, window_seconds=60)
        limiter.check("agent-a")
        limiter.check("agent-a")
        # agent-a is at limit, but agent-b should be fine
        limiter.check("agent-b")
        limiter.check("agent-b")
        with pytest.raises(ValueError, match="agent-a"):
            limiter.check("agent-a")
        with pytest.raises(ValueError, match="agent-b"):
            limiter.check("agent-b")


class TestRateLimiterReset:
    def test_reset_specific_agent(self):
        """Resetting one agent should not affect others."""
        limiter = RateLimiter(max_calls=2, window_seconds=60)
        limiter.check("agent-a")
        limiter.check("agent-a")
        limiter.check("agent-b")
        limiter.check("agent-b")

        # Both at limit
        with pytest.raises(ValueError):
            limiter.check("agent-a")

        # Reset agent-a only
        limiter.reset("agent-a")
        limiter.check("agent-a")  # should work now

        # agent-b still at limit
        with pytest.raises(ValueError):
            limiter.check("agent-b")

    def test_reset_all_agents(self):
        """Resetting all agents clears everything."""
        limiter = RateLimiter(max_calls=1, window_seconds=60)
        limiter.check("agent-a")
        limiter.check("agent-b")

        with pytest.raises(ValueError):
            limiter.check("agent-a")
        with pytest.raises(ValueError):
            limiter.check("agent-b")

        limiter.reset()
        limiter.check("agent-a")  # should work
        limiter.check("agent-b")  # should work


class TestRateLimiterWindowExpiry:
    def test_old_calls_pruned_after_window(self):
        """Calls older than window_seconds should be pruned, allowing new calls."""
        limiter = RateLimiter(max_calls=2, window_seconds=0.1)
        limiter.check("agent-a")
        limiter.check("agent-a")

        with pytest.raises(ValueError):
            limiter.check("agent-a")

        # Wait for window to expire
        time.sleep(0.15)

        # Old calls should be pruned, allowing new ones
        limiter.check("agent-a")  # should not raise

    def test_error_message_format(self):
        """Error message includes agent key and limits."""
        limiter = RateLimiter(max_calls=1, window_seconds=30.0)
        limiter.check("sess-1:security")
        with pytest.raises(
            ValueError,
            match=r"Rate limit exceeded for sess-1:security: max 1 calls per 30\.0s",
        ):
            limiter.check("sess-1:security")
