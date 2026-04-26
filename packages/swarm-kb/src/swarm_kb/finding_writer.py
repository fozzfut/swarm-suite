"""Generalized finding writer -- any tool can post findings to shared KB."""

import json
import logging
import threading
from pathlib import Path
from typing import Any

from swarm_core.ids import generate_id
from swarm_core.timeutil import now_iso

from .config import SuiteConfig

_log = logging.getLogger("swarm_kb.finding_writer")


class FindingWriter:
    """Write findings into a tool session's findings.jsonl.

    Writes to ~/.swarm-kb/sessions/<tool>/<session_id>/findings.jsonl
    """

    def __init__(
        self,
        tool: str,
        session_id: str,
        config: SuiteConfig | None = None,
    ) -> None:
        if config is None:
            config = SuiteConfig.load()
        self._tool = tool
        self._session_id = session_id
        self._session_dir = config.tool_sessions_path(tool) / session_id
        self._findings_path = self._session_dir / "findings.jsonl"
        self._lock = threading.Lock()

    def post(self, finding: dict[str, Any]) -> str:
        """Append a finding. Assigns ID if missing. Returns finding ID."""
        finding = dict(finding)  # defensive copy

        if not finding.get("id"):
            finding["id"] = generate_id("f", length=4)

        if not finding.get("created_at"):
            finding["created_at"] = now_iso()

        finding.setdefault("source_tool", self._tool)
        finding.setdefault("source_session", self._session_id)

        with self._lock:
            self._session_dir.mkdir(parents=True, exist_ok=True)
            with open(self._findings_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(finding) + "\n")

        _log.info(
            "Finding %s posted to %s/%s",
            finding["id"], self._tool, self._session_id,
        )
        return finding["id"]

    def post_batch(self, findings: list[dict[str, Any]]) -> list[str]:
        """Post multiple findings at once. Returns list of finding IDs."""
        ids: list[str] = []
        now = now_iso()
        entries: list[dict[str, Any]] = []

        for f in findings:
            f = dict(f)  # defensive copy
            if not f.get("id"):
                f["id"] = generate_id("f", length=4)
            if not f.get("created_at"):
                f["created_at"] = now
            f.setdefault("source_tool", self._tool)
            f.setdefault("source_session", self._session_id)
            entries.append(f)
            ids.append(f["id"])

        with self._lock:
            self._session_dir.mkdir(parents=True, exist_ok=True)
            with open(self._findings_path, "a", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(entry) + "\n")

        _log.info(
            "Batch posted %d findings to %s/%s",
            len(ids), self._tool, self._session_id,
        )
        return ids
