"""Adapter to convert ArchSwarm outputs into actionable findings for FixSwarm.

Reads arch sessions from swarm-kb (~/.swarm-kb/arch/sessions/) and converts
architectural metrics (coupling, complexity, circular deps) into findings
that fix experts can claim, propose fixes for, and apply.
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field

_log = logging.getLogger("fix_swarm.arch_adapter")


@dataclass
class ArchFinding:
    """An architectural issue converted into a fixable finding."""
    id: str = ""
    file: str = ""
    line_start: int = 1
    line_end: int = 1
    severity: str = "medium"
    category: str = "architecture"
    title: str = ""
    actual: str = ""
    expected: str = ""
    suggestion_action: str = "refactor"
    suggestion_detail: str = ""
    confidence: float = 0.7
    tags: list[str] = field(default_factory=list)
    arch_session_id: str = ""  # link back to arch session

    def to_finding_dict(self) -> dict:
        """Convert to a dict compatible with FixSwarm's finding format."""
        return {
            "id": self.id,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "actual": self.actual,
            "expected": self.expected,
            "suggestion_action": self.suggestion_action,
            "suggestion_detail": self.suggestion_detail,
            "confidence": self.confidence,
            "status": "open",
            "tags": self.tags,
            "arch_session_id": self.arch_session_id,
        }


def load_arch_session(session_id: str) -> dict | None:
    """Load an ArchSwarm session from swarm-kb storage.

    Returns dict with keys: meta (dict), transcript (str), analysis (dict or None).
    Returns None if session not found.
    """
    sessions_dir = Path("~/.swarm-kb/arch/sessions").expanduser()
    sess_dir = sessions_dir / session_id

    if not sess_dir.is_dir():
        return None

    result = {"session_id": session_id, "meta": {}, "transcript": "", "analysis": None}

    meta_path = sess_dir / "meta.json"
    if meta_path.exists():
        try:
            result["meta"] = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Failed to read arch meta %s: %s", meta_path, exc)

    transcript_path = sess_dir / "transcript.md"
    if transcript_path.exists():
        try:
            result["transcript"] = transcript_path.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning("Failed to read transcript %s: %s", transcript_path, exc)

    return result


def analyze_project_for_arch_findings(project_path: str, scope: str = "") -> list[ArchFinding]:
    """Run ArchSwarm's code scanner and convert metrics into findings.

    This is the main entry point — it imports arch_swarm.code_scanner,
    runs scan_project(), and converts the results into ArchFinding objects.
    """
    try:
        from arch_swarm.code_scanner import scan_project, ArchAnalysis
    except ImportError:
        _log.warning("arch-swarm-ai not installed, cannot scan for arch findings")
        return []

    analysis = scan_project(project_path, scope=scope or None)
    return _convert_analysis(analysis, project_path)


def _convert_analysis(analysis, project_path: str) -> list[ArchFinding]:
    """Convert an ArchAnalysis into a list of ArchFindings."""
    findings: list[ArchFinding] = []
    import secrets

    # Build coupling map for quick lookup
    coupling_map = {c.module: c for c in analysis.coupling}

    # 1. High efferent coupling (too many outgoing dependencies)
    for c in analysis.coupling:
        if c.efferent >= 8:
            sev = "high" if c.efferent >= 12 else "medium"
            mod = next((m for m in analysis.modules if m.name == c.module), None)
            file_path = mod.path if mod else c.module.replace(".", "/") + ".py"
            findings.append(ArchFinding(
                id="af-" + secrets.token_hex(3),
                file=file_path,
                severity=sev,
                category="architecture",
                title=f"High outgoing coupling: {c.module} ({c.efferent} dependencies)",
                actual=f"Module {c.module} imports {c.efferent} other project modules",
                expected="Modules should have low efferent coupling (< 8) for maintainability",
                suggestion_action="refactor",
                suggestion_detail=f"Break {c.module}'s {c.efferent} outgoing dependencies by extracting shared concerns into focused sub-modules",
                confidence=0.8,
                tags=["coupling", "modularity", "refactoring"],
            ))

    # 2. Circular dependencies
    circular = _find_circular_deps(analysis.dependency_graph)
    for (mod_a, mod_b) in circular:
        mod = next((m for m in analysis.modules if m.name == mod_a), None)
        file_path = mod.path if mod else mod_a.replace(".", "/") + ".py"
        findings.append(ArchFinding(
            id="af-" + secrets.token_hex(3),
            file=file_path,
            severity="high",
            category="architecture",
            title=f"Circular dependency: {mod_a} \u2194 {mod_b}",
            actual=f"{mod_a} imports {mod_b} and {mod_b} imports {mod_a}",
            expected="Dependencies should be acyclic (DAG) to prevent build/test fragility",
            suggestion_action="fix",
            suggestion_detail=f"Break cycle by extracting shared types/interfaces into a third module, or use dependency inversion (abstract interface in {mod_a}, implementation in {mod_b})",
            confidence=0.9,
            tags=["circular-dependency", "modularity", "architecture"],
        ))

    # 3. High complexity modules (bottleneck risk)
    for mod_name, complexity in analysis.complexity_scores.items():
        ca = coupling_map.get(mod_name)
        afferent = ca.afferent if ca else 0
        # Bottleneck = high complexity AND many dependents
        if complexity >= 30 and afferent >= 2:
            risk_score = complexity * afferent
            mod = next((m for m in analysis.modules if m.name == mod_name), None)
            file_path = mod.path if mod else mod_name.replace(".", "/") + ".py"
            findings.append(ArchFinding(
                id="af-" + secrets.token_hex(3),
                file=file_path,
                severity="high" if risk_score >= 100 else "medium",
                category="architecture",
                title=f"Bottleneck module: {mod_name} (complexity {complexity}, {afferent} dependents)",
                actual=f"{mod_name} has cyclomatic complexity {complexity} and is imported by {afferent} modules (risk score: {risk_score})",
                expected="High-traffic modules should have low complexity for safe modification",
                suggestion_action="refactor",
                suggestion_detail=f"Split {mod_name} into smaller, focused modules. Extract complex logic into helpers. Target complexity < 20.",
                confidence=0.75,
                tags=["complexity", "bottleneck", "refactoring"],
            ))
        elif complexity >= 50:
            # Very high complexity even without many dependents
            mod = next((m for m in analysis.modules if m.name == mod_name), None)
            file_path = mod.path if mod else mod_name.replace(".", "/") + ".py"
            findings.append(ArchFinding(
                id="af-" + secrets.token_hex(3),
                file=file_path,
                severity="medium",
                category="architecture",
                title=f"High complexity module: {mod_name} (complexity {complexity})",
                actual=f"{mod_name} has cyclomatic complexity {complexity}",
                expected="Modules should have cyclomatic complexity < 30 for readability",
                suggestion_action="refactor",
                suggestion_detail=f"Decompose {mod_name}: extract long functions, simplify conditional logic, consider strategy/state patterns",
                confidence=0.7,
                tags=["complexity", "refactoring"],
            ))

    # 4. Bloated modules (too many definitions)
    for mod in analysis.modules:
        total_defs = len(mod.classes) + len(mod.functions)
        if total_defs >= 15:
            findings.append(ArchFinding(
                id="af-" + secrets.token_hex(3),
                file=mod.path,
                severity="medium" if total_defs < 25 else "high",
                category="architecture",
                title=f"Bloated module: {mod.name} ({len(mod.classes)} classes, {len(mod.functions)} functions)",
                actual=f"{mod.name} has {total_defs} top-level definitions ({len(mod.classes)} classes, {len(mod.functions)} functions, {mod.lines} lines)",
                expected="Modules should have a single responsibility; aim for < 10 top-level definitions",
                suggestion_action="refactor",
                suggestion_detail=f"Split {mod.name} by responsibility: group related classes/functions into sub-modules",
                confidence=0.7,
                tags=["bloated-module", "srp", "refactoring"],
            ))

    # 5. Unstable modules (high instability + high efferent)
    for c in analysis.coupling:
        if c.instability > 0.8 and c.efferent >= 5:
            mod = next((m for m in analysis.modules if m.name == c.module), None)
            file_path = mod.path if mod else c.module.replace(".", "/") + ".py"
            findings.append(ArchFinding(
                id="af-" + secrets.token_hex(3),
                file=file_path,
                severity="medium",
                category="architecture",
                title=f"Unstable module: {c.module} (I={c.instability:.2f}, Ce={c.efferent})",
                actual=f"{c.module} has instability {c.instability:.2f} (efferent={c.efferent}, afferent={c.afferent})",
                expected="Core modules should have low instability (I < 0.5) to resist change propagation",
                suggestion_action="refactor",
                suggestion_detail=f"Reduce {c.module}'s outgoing dependencies by introducing abstractions (interfaces/protocols) or moving logic closer to its dependencies",
                confidence=0.65,
                tags=["instability", "coupling", "refactoring"],
            ))

    return findings


def extract_debate_findings(session_id: str) -> list[ArchFinding]:
    """Extract actionable findings from a debate session's decision and critiques.

    Parses the transcript for specific action items from the winning decision
    and high-severity critiques.
    """
    session = load_arch_session(session_id)
    if not session:
        return []

    findings: list[ArchFinding] = []
    meta = session.get("meta", {})
    transcript = session.get("transcript", "")
    import secrets

    # The debate decision itself is an architectural recommendation
    decision_title = meta.get("decision")
    topic = meta.get("topic", "")

    if decision_title and meta.get("status") == "accepted":
        findings.append(ArchFinding(
            id="af-" + secrets.token_hex(3),
            severity="medium",
            category="architecture",
            title=f"Architectural decision: {decision_title}",
            actual=f"Debate topic: {topic}",
            expected=f"Implement the accepted decision: {decision_title}",
            suggestion_action="refactor",
            suggestion_detail=f"Apply the architectural recommendation from debate session {session_id}. See transcript for full context and trade-offs discussed.",
            confidence=0.6,
            tags=["arch-decision", "debate", "architecture"],
            arch_session_id=session_id,
        ))

    return findings


def _find_circular_deps(dep_graph: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Find circular dependency pairs in a dependency graph."""
    circular: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    all_modules = set(dep_graph.keys())

    for mod_a, imports in dep_graph.items():
        for imp in imports:
            # Check direct cycles: A imports B and B imports A
            if imp in all_modules and mod_a in dep_graph.get(imp, []):
                pair = tuple(sorted([mod_a, imp]))
                if pair not in seen:
                    seen.add(pair)
                    circular.append((mod_a, imp))

    return circular
