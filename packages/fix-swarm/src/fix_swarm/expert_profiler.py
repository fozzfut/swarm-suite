"""Expert profile loading and finding analysis for fix expert suggestions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_BUILTIN_DIR = Path(__file__).parent / "experts"


class FixExpertProfiler:
    def __init__(self, custom_dirs: list[Path] | None = None):
        self._custom_dirs = custom_dirs or []

    def list_profiles(self) -> list[dict]:
        """List all available fix expert profiles."""
        profiles = []
        for yaml_file in sorted(_BUILTIN_DIR.glob("*.yaml")):
            profiles.append(self._load_yaml(yaml_file))
        for d in self._custom_dirs:
            if d.exists():
                for yaml_file in sorted(d.glob("*.yaml")):
                    profiles.append(self._load_yaml(yaml_file))
        return profiles

    def load_profile(self, name: str) -> dict:
        """Load a single profile by name."""
        path = _BUILTIN_DIR / f"{name}.yaml"
        if path.exists():
            return self._load_yaml(path)
        for d in self._custom_dirs:
            path = d / f"{name}.yaml"
            if path.exists():
                return self._load_yaml(path)
        raise FileNotFoundError(f"Fix expert profile '{name}' not found")

    def suggest_experts(self, findings: list[dict]) -> list[dict]:
        """Analyze findings and suggest relevant fix experts.

        Each finding is a dict with keys: category, tags, severity, title, file, etc.
        Returns sorted list of expert suggestions with confidence scores.
        """
        # Map finding categories/tags to expert profiles
        # E.g., security findings -> security-fix, performance -> performance-fix
        category_to_expert = {
            "security": "security-fix",
            "injection": "security-fix",
            "auth": "security-fix",
            "xss": "security-fix",
            "csrf": "security-fix",
            "performance": "performance-fix",
            "n+1": "performance-fix",
            "blocking": "performance-fix",
            "quadratic": "performance-fix",
            "caching": "performance-fix",
            "type-safety": "type-fix",
            "nullable": "type-fix",
            "type": "type-fix",
            "cast": "type-fix",
            "error-handling": "error-handling-fix",
            "swallowed-error": "error-handling-fix",
            "broad-catch": "error-handling-fix",
            "exception": "error-handling-fix",
            "test": "test-fix",
            "assertion": "test-fix",
            "flaky": "test-fix",
            "mock": "test-fix",
            "dependency": "dependency-fix",
            "deprecated": "dependency-fix",
            "vulnerability": "dependency-fix",
            "version": "dependency-fix",
            "compatibility": "compatibility-fix",
            "compat": "compatibility-fix",
            "platform": "compatibility-fix",
            "consistency": "refactoring",
            "dead-code": "refactoring",
            "style": "refactoring",
            "design": "refactoring",
            "duplication": "refactoring",
            "architecture": "refactoring",
            "coupling": "refactoring",
            "circular-dependency": "refactoring",
            "complexity": "refactoring",
            "bloated-module": "refactoring",
            "instability": "refactoring",
            "modularity": "refactoring",
            "srp": "refactoring",
            "arch-decision": "refactoring",
            "bottleneck": "performance-fix",
        }

        # Score each expert based on how many findings match
        expert_scores: dict[str, float] = {}
        expert_finding_count: dict[str, int] = {}

        for finding in findings:
            category = finding.get("category", "").lower()
            tags = [t.lower() for t in finding.get("tags", [])]
            title = finding.get("title", "").lower()

            matched_experts: set[str] = set()

            # Match by category, tags, and title
            for key, expert in category_to_expert.items():
                if key in category or any(key in tag for tag in tags) or key in title:
                    matched_experts.add(expert)

            # Default: refactoring expert handles anything not matched
            if not matched_experts:
                matched_experts.add("refactoring")

            for expert in matched_experts:
                expert_scores[expert] = expert_scores.get(expert, 0) + 0.2
                expert_finding_count[expert] = expert_finding_count.get(expert, 0) + 1

        # Build suggestions from profiles that have matching findings
        suggestions = []
        for profile in self.list_profiles():
            profile_name = Path(profile.get("_source_file", "")).stem
            score = min(expert_scores.get(profile_name, 0), 1.0)
            count = expert_finding_count.get(profile_name, 0)
            if score > 0:
                suggestions.append({
                    "profile_name": profile_name,
                    "name": profile["name"],
                    "description": profile.get("description", ""),
                    "confidence": score,
                    "matching_findings": count,
                })

        suggestions.sort(key=lambda s: s["confidence"], reverse=True)
        return suggestions

    def _load_yaml(self, path: Path) -> dict:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            return {"name": path.stem, "description": "Error loading", "_source_file": str(path)}
        if not isinstance(data, dict):
            return {"name": path.stem, "description": "Invalid format", "_source_file": str(path)}
        data["_source_file"] = str(path)
        return data
