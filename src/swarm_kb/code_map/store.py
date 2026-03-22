"""Code map persistence -- JSONL storage with TTL cache."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .models import CouplingMetrics, ProjectCodeMap, UnifiedModuleInfo

_log = logging.getLogger("swarm_kb.code_map.store")


class CodeMapStore:
    """Read/write ProjectCodeMap to disk under code-map/{project_hash}/."""

    def __init__(self, base_dir: Path) -> None:
        self._base = Path(base_dir)

    def save(self, code_map: ProjectCodeMap) -> None:
        """Persist a ProjectCodeMap atomically."""
        self._base.mkdir(parents=True, exist_ok=True)

        # meta.json
        meta = {
            "root": code_map.root,
            "scanned_at": code_map.scanned_at,
            "total_modules": code_map.total_modules,
            "total_lines": code_map.total_lines,
        }
        self._atomic_write(self._base / "meta.json", json.dumps(meta, indent=2))

        # modules.jsonl
        lines = [json.dumps(m.to_dict()) for m in code_map.modules]
        self._atomic_write(self._base / "modules.jsonl", "\n".join(lines) + "\n" if lines else "")

        # dependency_graph.json
        self._atomic_write(
            self._base / "dependency_graph.json",
            json.dumps(code_map.dependency_graph, indent=2),
        )

        # coupling.json
        self._atomic_write(
            self._base / "coupling.json",
            json.dumps([c.to_dict() for c in code_map.coupling], indent=2),
        )

        # complexity.json
        self._atomic_write(
            self._base / "complexity.json",
            json.dumps(code_map.complexity_scores, indent=2),
        )

        # class_hierarchy.json
        self._atomic_write(
            self._base / "class_hierarchy.json",
            json.dumps(code_map.class_hierarchy, indent=2),
        )

        _log.info("Code map saved to %s (%d modules)", self._base, code_map.total_modules)

    def load(self) -> ProjectCodeMap | None:
        """Load a ProjectCodeMap from disk, or None if not found."""
        meta_path = self._base / "meta.json"
        if not meta_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("Failed to read code map meta: %s", exc)
            return None

        modules: list[UnifiedModuleInfo] = []
        modules_path = self._base / "modules.jsonl"
        if modules_path.exists():
            for line in modules_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        modules.append(UnifiedModuleInfo.from_dict(json.loads(line)))
                    except Exception as exc:
                        _log.warning("Skipping corrupt module line: %s", exc)

        dep_graph = self._load_json(self._base / "dependency_graph.json", {})
        coupling_raw = self._load_json(self._base / "coupling.json", [])
        complexity = self._load_json(self._base / "complexity.json", {})
        hierarchy = self._load_json(self._base / "class_hierarchy.json", {})

        return ProjectCodeMap(
            root=meta.get("root", ""),
            scanned_at=meta.get("scanned_at", ""),
            modules=modules,
            dependency_graph=dep_graph,
            coupling=[CouplingMetrics.from_dict(c) for c in coupling_raw],
            class_hierarchy=hierarchy,
            complexity_scores=complexity,
        )

    def is_fresh(self, ttl_hours: float = 1.0) -> bool:
        """Check if the stored code map is still within TTL."""
        meta_path = self._base / "meta.json"
        if not meta_path.exists():
            return False

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            scanned_at = datetime.fromisoformat(meta["scanned_at"])
            age_hours = (datetime.now(timezone.utc) - scanned_at).total_seconds() / 3600
            return age_hours < ttl_hours
        except Exception:
            return False

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content to file atomically via tempfile + replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
        except Exception:
            os.close(tmp_fd)
            os.unlink(tmp_path)
            raise
        try:
            with fh:
                fh.write(content)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("Failed to load %s: %s", path, exc)
            return default
