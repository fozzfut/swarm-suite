"""Universal quality gate for the review-fix cycle.

Defines thresholds for when code is "good enough" to advance in the pipeline,
and circuit breaker logic to prevent infinite fix loops.

Bug categories that count toward the gate (code bugs):
  logic, type-safety, thread-safety, security, error-handling,
  data-integrity, regression, api-mismatch

Categories that do NOT count (non-code):
  architecture, style, documentation, dead-code, cosmetic, design, observation
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("swarm_kb.quality_gate")

# Categories that count as "code bugs" for the quality gate
CODE_BUG_CATEGORIES = {
    "bug", "logic", "type-safety", "type_safety", "thread-safety", "thread_safety",
    "security", "injection", "path-traversal", "error-handling", "error_handling",
    "data-integrity", "data_integrity", "regression", "api-mismatch", "api_mismatch",
    "race-condition", "race_condition", "swallowed-error", "broad-catch",
    "missing-validation", "null-check", "type-mismatch",
}

# Categories that are explicitly excluded
NON_CODE_CATEGORIES = {
    "architecture", "style", "documentation", "dead-code", "dead_code",
    "cosmetic", "design", "observation", "naming", "formatting",
    "import-order", "comment", "docstring",
}

SEVERITY_WEIGHTS = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}


@dataclass
class GateThresholds:
    """Configurable thresholds for the quality gate."""
    # Per-round maximums
    max_critical: int = 0
    max_high: int = 0
    max_medium: int = 3
    max_low: int = -1           # -1 = unlimited

    # Weighted score: sum of (severity_weight * count) must be <= this
    max_weighted_score: int = 8

    # Stability: N consecutive rounds must meet thresholds
    consecutive_clean_rounds: int = 2

    # Regression protection
    max_regression_rate: float = 0.10  # max 10% of fixes introduce new bugs

    # Circuit breaker
    max_iterations: int = 7     # absolute maximum review-fix cycles
    max_stale_rounds: int = 3   # if same bugs keep appearing N times, stop
    score_increase_limit: int = 2  # if score increases N rounds in a row, stop

    def to_dict(self) -> dict:
        return {
            "max_critical": self.max_critical,
            "max_high": self.max_high,
            "max_medium": self.max_medium,
            "max_low": self.max_low,
            "max_weighted_score": self.max_weighted_score,
            "consecutive_clean_rounds": self.consecutive_clean_rounds,
            "max_regression_rate": self.max_regression_rate,
            "max_iterations": self.max_iterations,
            "max_stale_rounds": self.max_stale_rounds,
            "score_increase_limit": self.score_increase_limit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GateThresholds":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RoundMetrics:
    """Metrics for a single review-fix round."""
    round_number: int = 0
    total_findings: int = 0
    code_bugs: int = 0          # only CODE_BUG_CATEGORIES
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0
    weighted_score: int = 0
    fixes_applied: int = 0
    regressions_introduced: int = 0
    regression_rate: float = 0.0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class GateResult:
    """Result of checking the quality gate."""
    passed: bool = False
    reason: str = ""
    metrics: RoundMetrics = field(default_factory=RoundMetrics)
    thresholds: GateThresholds = field(default_factory=GateThresholds)
    history: list[dict] = field(default_factory=list)  # previous rounds

    # Circuit breaker
    circuit_broken: bool = False
    circuit_reason: str = ""

    # Recommendations
    recommendation: str = ""  # "continue", "stop_clean", "stop_circuit_breaker"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "metrics": self.metrics.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "history": self.history,
            "circuit_broken": self.circuit_broken,
            "circuit_reason": self.circuit_reason,
            "recommendation": self.recommendation,
        }


def classify_finding(finding: dict) -> bool:
    """Return True if this finding counts as a 'code bug' for the quality gate."""
    category = finding.get("category", "").lower().strip()
    tags = [t.lower().strip() for t in finding.get("tags", [])]

    # Explicit code bug category
    if category in CODE_BUG_CATEGORIES:
        return True

    # Explicit non-code category
    if category in NON_CODE_CATEGORIES:
        return False

    # Check tags for code bug signals
    if any(t in CODE_BUG_CATEGORIES for t in tags):
        return True

    # Check tags for non-code signals
    if any(t in NON_CODE_CATEGORIES for t in tags):
        return False

    # Default: if severity is critical or high, treat as code bug
    severity = finding.get("severity", "medium").lower()
    if severity in ("critical", "high"):
        return True

    # Unknown category with medium/low severity: count it (conservative)
    return True


def compute_round_metrics(
    findings: list[dict],
    fixes_applied: int = 0,
    regressions: int = 0,
) -> RoundMetrics:
    """Compute metrics for a single review round."""
    metrics = RoundMetrics(
        total_findings=len(findings),
        fixes_applied=fixes_applied,
        regressions_introduced=regressions,
    )

    for f in findings:
        if not classify_finding(f):
            continue

        metrics.code_bugs += 1
        severity = f.get("severity", "medium").lower()

        if severity == "critical":
            metrics.critical += 1
        elif severity == "high":
            metrics.high += 1
        elif severity == "medium":
            metrics.medium += 1
        elif severity == "low":
            metrics.low += 1
        else:
            metrics.info += 1

        metrics.weighted_score += SEVERITY_WEIGHTS.get(severity, 0)

    if fixes_applied > 0:
        metrics.regression_rate = round(regressions / fixes_applied, 3)

    return metrics


def check_gate(
    current_metrics: RoundMetrics,
    history: list[RoundMetrics] = None,
    thresholds: GateThresholds = None,
) -> GateResult:
    """Check if the quality gate is met.

    Returns GateResult with:
    - passed: True if all thresholds met AND stability confirmed
    - circuit_broken: True if the fix cycle should stop regardless
    - recommendation: "continue", "stop_clean", or "stop_circuit_breaker"
    """
    if thresholds is None:
        thresholds = GateThresholds()
    if history is None:
        history = []

    m = current_metrics
    result = GateResult(
        metrics=m,
        thresholds=thresholds,
        history=[h.to_dict() for h in history],
    )

    round_num = len(history) + 1
    m.round_number = round_num

    # -- Circuit breaker checks (stop even if not clean) --

    # 1. Maximum iterations reached
    if round_num >= thresholds.max_iterations:
        result.circuit_broken = True
        result.circuit_reason = (
            f"Maximum iterations ({thresholds.max_iterations}) reached. "
            f"Current round {round_num}. Remaining issues: "
            f"{m.critical}C {m.high}H {m.medium}M {m.low}L"
        )
        result.recommendation = "stop_circuit_breaker"
        return result

    # 2. Score increasing over N rounds (fixes making things worse)
    if len(history) >= thresholds.score_increase_limit:
        recent_scores = [h.weighted_score for h in history[-thresholds.score_increase_limit:]]
        recent_scores.append(m.weighted_score)
        increasing = all(
            recent_scores[i] < recent_scores[i + 1]
            for i in range(len(recent_scores) - 1)
        )
        if increasing:
            result.circuit_broken = True
            result.circuit_reason = (
                f"Weighted score increased {thresholds.score_increase_limit} rounds in a row: "
                + " -> ".join(str(s) for s in recent_scores)
                + ". Fixes are introducing more bugs than they solve."
            )
            result.recommendation = "stop_circuit_breaker"
            return result

    # 3. High regression rate
    if m.fixes_applied > 0 and m.regression_rate > thresholds.max_regression_rate:
        # Check if this is persistent (not just one bad round)
        high_regression_count = sum(
            1 for h in history
            if h.fixes_applied > 0 and h.regression_rate > thresholds.max_regression_rate
        )
        if high_regression_count >= 2:  # 3rd consecutive high-regression round
            result.circuit_broken = True
            result.circuit_reason = (
                f"Regression rate > {thresholds.max_regression_rate:.0%} for "
                f"{high_regression_count + 1} rounds. Fix process is unstable."
            )
            result.recommendation = "stop_circuit_breaker"
            return result

    # 4. Stale rounds (same bug count keeps appearing)
    if len(history) >= thresholds.max_stale_rounds:
        recent_bugs = [h.code_bugs for h in history[-thresholds.max_stale_rounds:]]
        recent_bugs.append(m.code_bugs)
        if len(set(recent_bugs)) == 1 and recent_bugs[0] > 0:
            result.circuit_broken = True
            result.circuit_reason = (
                f"Same bug count ({recent_bugs[0]}) for "
                f"{thresholds.max_stale_rounds + 1} consecutive rounds. "
                f"Review-fix cycle is not making progress."
            )
            result.recommendation = "stop_circuit_breaker"
            return result

    # -- Quality threshold checks --

    failures = []

    if m.critical > thresholds.max_critical:
        failures.append(f"critical={m.critical} (max {thresholds.max_critical})")

    if m.high > thresholds.max_high:
        failures.append(f"high={m.high} (max {thresholds.max_high})")

    if thresholds.max_medium >= 0 and m.medium > thresholds.max_medium:
        failures.append(f"medium={m.medium} (max {thresholds.max_medium})")

    if thresholds.max_low >= 0 and m.low > thresholds.max_low:
        failures.append(f"low={m.low} (max {thresholds.max_low})")

    if m.weighted_score > thresholds.max_weighted_score:
        failures.append(f"weighted_score={m.weighted_score} (max {thresholds.max_weighted_score})")

    if failures:
        result.passed = False
        result.reason = "Thresholds exceeded: " + ", ".join(failures)
        result.recommendation = "continue"
        return result

    # -- Stability check (consecutive clean rounds) --

    clean_streak = 1  # current round is clean
    for h in reversed(history):
        h_failures = []
        if h.critical > thresholds.max_critical:
            h_failures.append("critical")
        if h.high > thresholds.max_high:
            h_failures.append("high")
        if thresholds.max_medium >= 0 and h.medium > thresholds.max_medium:
            h_failures.append("medium")
        if h.weighted_score > thresholds.max_weighted_score:
            h_failures.append("score")

        if h_failures:
            break
        clean_streak += 1

    if clean_streak >= thresholds.consecutive_clean_rounds:
        result.passed = True
        result.reason = (
            f"Quality gate PASSED. {clean_streak} consecutive clean rounds "
            f"(required: {thresholds.consecutive_clean_rounds}). "
            f"Current: {m.critical}C {m.high}H {m.medium}M {m.low}L, "
            f"score={m.weighted_score}"
        )
        result.recommendation = "stop_clean"
        return result

    # Thresholds met but not enough consecutive clean rounds yet
    result.passed = False
    result.reason = (
        f"Thresholds met this round, but need "
        f"{thresholds.consecutive_clean_rounds - clean_streak} more clean round(s) "
        f"for stability. ({clean_streak}/{thresholds.consecutive_clean_rounds})"
    )
    result.recommendation = "continue"
    return result


def load_thresholds(path: Path) -> GateThresholds:
    """Load thresholds from a JSON file. Returns defaults if not found."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GateThresholds.from_dict(data)
        except Exception as exc:
            _log.warning("Failed to load thresholds from %s: %s", path, exc)
    return GateThresholds()


def save_thresholds(thresholds: GateThresholds, path: Path) -> None:
    """Save thresholds to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(thresholds.to_dict(), indent=2), encoding="utf-8")
