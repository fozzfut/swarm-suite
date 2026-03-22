"""Expert profile loading and project analysis for expert suggestions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .logging_config import get_logger

_log = get_logger("expert_profiler")
_BUILTIN_DIR = Path(__file__).parent / "experts"


class ExpertProfiler:
    def __init__(self, custom_dirs: list[Path] | None = None):
        self._custom_dirs = custom_dirs or []

    def list_profiles(self) -> list[dict]:
        profiles = []
        for yaml_file in sorted(_BUILTIN_DIR.glob("*.yaml")):
            profiles.append(self._load_yaml(yaml_file))
        for d in self._custom_dirs:
            if d.exists():
                for yaml_file in sorted(d.glob("*.yaml")):
                    profiles.append(self._load_yaml(yaml_file))
        return profiles

    def load_profile(self, name: str) -> dict:
        # Check built-in first
        path = _BUILTIN_DIR / f"{name}.yaml"
        if path.exists():
            return self._load_yaml(path)
        # Check custom dirs
        for d in self._custom_dirs:
            path = d / f"{name}.yaml"
            if path.exists():
                return self._load_yaml(path)
        raise FileNotFoundError(f"Expert profile '{name}' not found")

    def suggest_experts(self, project_path: str) -> list[dict]:
        proj = Path(project_path)
        if not proj.exists():
            return []

        # Collect all source file contents for analysis
        file_contents: dict[str, str] = {}
        source_exts = (
            "*.py", "*.js", "*.ts", "*.tsx", "*.jsx",
            "*.go", "*.rs", "*.java", "*.kt", "*.kts",
            "*.cs", "*.cpp", "*.c", "*.h", "*.hpp",
            "*.rb", "*.ex", "*.exs", "*.swift", "*.php",
        )
        skip_dirs = {
            "node_modules", ".venv", "__pycache__", ".git",
            "target", "build", "dist", "vendor", "bin", "obj",
            ".mypy_cache", ".pytest_cache", ".tox",
            ".eggs", "site-packages",
        }
        for ext in source_exts:
            for f in proj.rglob(ext):
                try:
                    rel_parts = f.relative_to(proj).parts
                except ValueError:
                    continue
                if any(part in skip_dirs for part in rel_parts):
                    continue
                try:
                    file_contents[str(f.relative_to(proj))] = f.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                except Exception as exc:
                    _log.warning("Skipping file %s: %s", f, exc)
                    continue

        has_tests = (
            (proj / "tests").exists() and any((proj / "tests").rglob("*"))
        ) or (
            (proj / "test").exists() and any((proj / "test").rglob("*"))
        ) or (
            (proj / "spec").exists() and any((proj / "spec").rglob("*"))
        )

        all_text = "\n".join(file_contents.values())

        suggestions = []
        for profile in self.list_profiles():
            score = self._score_relevance(profile, file_contents, all_text, has_tests)
            if score > 0:
                profile_name = Path(profile.get("_source_file", "")).stem
                suggestions.append({
                    "profile_name": profile_name,
                    "name": profile["name"],
                    "description": profile.get("description", ""),
                    "confidence": min(score, 1.0),
                })

        suggestions.sort(key=lambda s: s["confidence"], reverse=True)
        return suggestions

    def _score_relevance(
        self, profile: dict, file_contents: dict[str, str],
        all_text: str, has_tests: bool,
    ) -> float:
        score = 0.0
        signals = profile.get("relevance_signals", {})
        import_signals = signals.get("imports", [])
        pattern_signals = signals.get("patterns", [])

        # Check imports (language-agnostic patterns)
        import_patterns = [
            "import {imp}",      # Python, Java, Go, Kotlin, Swift
            "from {imp}",        # Python
            "require('{imp}'",   # Node CJS
            'require("{imp}"',   # Node CJS
            "require '{imp}'",   # Ruby
            'require "{imp}"',   # Ruby
            'use {imp}',         # Rust, Perl, PHP
            '#include "{imp}"',  # C/C++
            '#include <{imp}>',  # C/C++
            'using {imp}',       # C#
        ]
        for imp in import_signals:
            for pat_template in import_patterns:
                if pat_template.format(imp=imp) in all_text:
                    score += 0.3
                    break  # count each import signal once

        # Check patterns
        for pat in pattern_signals:
            try:
                if re.search(pat, all_text):
                    score += 0.2
            except re.error:
                continue

        # Base score for universal experts (always relevant for code projects)
        if file_contents:
            name = profile.get("name", "").lower()
            # Experts that are relevant to ANY codebase
            if any(kw in name for kw in (
                "contract", "signature",    # API contract
                "cross-reference", "consistency",  # Cross-file consistency
                "dead code",                # Dead code detection
                "dependency", "drift",      # Dependency drift
                "project context",          # Documentation accuracy
            )):
                score = max(score, 0.5)

            # Test quality expert boosted when tests exist
            if "test quality" in name and has_tests:
                score = max(score, 0.7)

        # Manifest-based boost for dependency expert
        if file_contents:
            name = profile.get("name", "").lower()
            if "dependency" in name or "drift" in name:
                manifest_files = {
                    "pyproject.toml", "requirements.txt", "package.json",
                    "Cargo.toml", "go.mod", "Gemfile", "pom.xml",
                    "build.gradle", "build.gradle.kts", "composer.json",
                    "mix.exs",
                }
                if any(f in file_contents for f in manifest_files):
                    score = max(score, 0.7)

        return score

    def _load_yaml(self, path: Path) -> dict:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            _log.warning("Corrupt expert profile %s: %s", path, exc)
            return {"name": path.stem, "description": f"Error loading: {exc}", "_source_file": str(path)}
        if not isinstance(data, dict):
            _log.warning("Expert profile %s is not a dict, skipping", path)
            return {"name": path.stem, "description": "Invalid format", "_source_file": str(path)}
        data["_source_file"] = str(path)
        return data
