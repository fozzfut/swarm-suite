"""Expert profile loading for monitor-swarm.

Mirrors spec-swarm's ExpertProfiler shape: read YAML files from
``experts/`` (builtin + optional custom dirs), return them as dicts,
support relevance scoring against a project scope.

Experts shipped (v0.2):

* ``timing-analyst`` -- post-trace: interprets violation findings.
* ``logging-instrumentation`` -- pre-trace: reviews source for
  blind paths, hot-path noise, missing context, sensitive data
  leakage in logs.
* ``telemetry-architect`` -- pre-trace: chooses + reviews the
  output channel (RTT/UART/ITM/syslog/...), throughput budget,
  failure modes.
* ``trace-format-designer`` -- pre-trace: timestamps, structure
  (text/JSON/defmt), correlation IDs, parseability vs human
  readability trade-off.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

_log = logging.getLogger("monitor_swarm.expert_profiler")
_BUILTIN_DIR = Path(__file__).parent / "experts"


class ExpertProfiler:
    """Load + suggest monitor-swarm expert profiles."""

    def __init__(self, custom_dirs: list[Path] | None = None) -> None:
        self._custom_dirs = list(custom_dirs or [])

    def _load_yaml(self, path: Path) -> dict:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            _log.warning("Skipping malformed expert %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        data["slug"] = path.stem
        return data

    def list_profiles(self) -> list[dict]:
        out: list[dict] = []
        for yfile in sorted(_BUILTIN_DIR.glob("*.yaml")):
            d = self._load_yaml(yfile)
            if d:
                out.append(d)
        for d in self._custom_dirs:
            if d.is_dir():
                for yfile in sorted(d.glob("*.yaml")):
                    p = self._load_yaml(yfile)
                    if p:
                        out.append(p)
        return out

    def load_profile(self, slug: str) -> dict:
        for d in [_BUILTIN_DIR, *self._custom_dirs]:
            path = d / f"{slug}.yaml"
            if path.is_file():
                p = self._load_yaml(path)
                if p:
                    return p
        raise FileNotFoundError(f"monitor expert '{slug}' not found")

    def suggest_experts(
        self,
        project_path: str | Path,
        max_files: int = 200,
    ) -> list[dict]:
        """Return experts ranked by relevance to the project.

        Heuristic: count files matching each expert's ``file_patterns``
        (excluding ``exclude_patterns``); count occurrences of each
        ``relevance_signals.imports`` / ``patterns`` regex in those
        files. Score = file_match_count + 2*signal_hits, capped.
        """
        base = Path(project_path)
        if not base.is_dir():
            return []

        profiles = self.list_profiles()
        results: list[dict] = []

        # Collect a bounded pool of source files to scan.
        all_files: list[Path] = []
        for ext in (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp",
                    ".hxx", ".rs", ".py", ".go", ".js", ".ts", ".tsx",
                    ".java", ".cs", ".swift"):
            for p in base.rglob(f"*{ext}"):
                if any(part in {"node_modules", ".venv", "target",
                                "build", "dist", ".git", "__pycache__"}
                       for part in p.parts):
                    continue
                all_files.append(p)
                if len(all_files) >= max_files:
                    break
            if len(all_files) >= max_files:
                break

        for prof in profiles:
            slug = prof.get("slug", "")
            file_patterns = prof.get("file_patterns") or []
            exclude_patterns = prof.get("exclude_patterns") or []
            signals = prof.get("relevance_signals") or {}
            imports = signals.get("imports") or []
            patterns = signals.get("patterns") or []

            file_hits = 0
            signal_hits = 0
            scanned = 0

            for fp in all_files:
                rel = fp.relative_to(base).as_posix()
                if not _matches_any(rel, file_patterns):
                    continue
                if _matches_any(rel, exclude_patterns):
                    continue
                file_hits += 1
                # Only deep-scan a sample to keep this fast
                if scanned >= 50:
                    continue
                try:
                    text = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                scanned += 1
                for imp in imports:
                    if imp and imp in text:
                        signal_hits += 1
                for pat in patterns:
                    try:
                        if re.search(pat, text):
                            signal_hits += 1
                    except re.error:
                        pass

            score = file_hits + 2 * signal_hits
            results.append({
                "slug": slug,
                "name": prof.get("name", slug),
                "description": prof.get("description", ""),
                "file_hits": file_hits,
                "signal_hits": signal_hits,
                "score": score,
                "uses_skills": list(prof.get("uses_skills") or []),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results


def _matches_any(rel_path: str, glob_patterns: list[str]) -> bool:
    """Lightweight ``fnmatch``-style match supporting ``**``."""
    import fnmatch
    for pat in glob_patterns:
        # Translate '**' to '*' for fnmatch (which is recursive-like already
        # for most practical purposes when used with rglob outputs).
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, pat.replace("**/", "")):
            return True
    return False
