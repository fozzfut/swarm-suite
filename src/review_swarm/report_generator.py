"""Markdown and JSON report generation from findings."""

from __future__ import annotations

import json
from collections import defaultdict

from .finding_store import FindingStore
from .models import Finding, Severity, Status


class ReportGenerator:
    def __init__(self, store: FindingStore) -> None:
        self._store = store

    def generate(self, session_id: str, fmt: str = "markdown") -> str:
        findings = self._store.get()
        if fmt == "json":
            return self._generate_json(findings)
        return self._generate_markdown(findings)

    def _generate_markdown(self, findings: list[Finding]) -> str:
        lines: list[str] = []
        lines.append("# Review Report\n")

        # Executive Summary
        lines.append("## Executive Summary\n")
        total = len(findings)
        by_sev: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        for f in findings:
            by_sev[f.severity.value] += 1
            by_status[f.status.value] += 1

        lines.append(f"**{total} findings** total\n")
        if total > 0:
            sev_parts = []
            for s in ["critical", "high", "medium", "low", "info"]:
                if by_sev[s] > 0:
                    sev_parts.append(f"{by_sev[s]} {s}")
            lines.append(f"By severity: {', '.join(sev_parts)}\n")

            status_parts = []
            for s in ["confirmed", "disputed", "open", "duplicate", "fixed", "wontfix"]:
                if by_status[s] > 0:
                    status_parts.append(f"{by_status[s]} {s}")
            if status_parts:
                lines.append(f"By status: {', '.join(status_parts)}\n")

        # Critical & High
        crit_high = [
            f for f in findings
            if f.severity in (Severity.CRITICAL, Severity.HIGH)
        ]
        if crit_high:
            lines.append("## Critical & High Findings\n")
            confirmed = [f for f in crit_high if f.status == Status.CONFIRMED]
            rest = [f for f in crit_high if f.status != Status.CONFIRMED]
            for f in confirmed + rest:
                lines.append(self._format_finding(f))

        # Disputed
        disputed = [f for f in findings if f.status == Status.DISPUTED]
        if disputed:
            lines.append("## Disputed Findings\n")
            for f in disputed:
                lines.append(self._format_finding(f))

        # Per-file breakdown
        by_file: dict[str, list] = defaultdict(list)
        for f in findings:
            by_file[f.file].append(f)

        if by_file:
            lines.append("## Per-File Breakdown\n")
            for file_path in sorted(by_file.keys()):
                file_findings = by_file[file_path]
                lines.append(f"### {file_path} ({len(file_findings)} findings)\n")
                for f in file_findings:
                    lines.append(
                        f"- **[{f.severity.value.upper()}]** {f.title} "
                        f"(L{f.line_start}-{f.line_end}, {f.status.value})\n"
                    )

        # Expert coverage
        by_expert: dict[str, set] = defaultdict(set)
        for f in findings:
            by_expert[f.expert_role].add(f.file)

        if by_expert:
            lines.append("## Expert Coverage\n")
            for expert, files in sorted(by_expert.items()):
                lines.append(f"- **{expert}**: {len(files)} files reviewed\n")

        return "\n".join(lines)

    def _format_finding(self, f: Finding) -> str:
        status_tag = f" [{f.status.value}]" if f.status != Status.OPEN else ""
        return (
            f"### {f.title}{status_tag}\n\n"
            f"- **Severity:** {f.severity.value} | **Category:** {f.category.value}\n"
            f"- **File:** `{f.file}:{f.line_start}-{f.line_end}`\n"
            f"- **Actual:** {f.actual}\n"
            f"- **Expected:** {f.expected}\n"
            f"- **Source:** `{f.source_ref}`\n"
            f"- **Suggestion:** [{f.suggestion_action.value}] {f.suggestion_detail}\n"
            f"- **Confidence:** {f.confidence:.0%}\n\n"
        )

    def _generate_json(self, findings: list[Finding]) -> str:
        by_sev: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        for f in findings:
            by_sev[f.severity.value] += 1
            by_status[f.status.value] += 1
        return json.dumps({
            "summary": {
                "total": len(findings),
                "by_severity": dict(by_sev),
                "by_status": dict(by_status),
            },
            "findings": [f.to_dict() for f in findings],
        }, indent=2, ensure_ascii=False)
