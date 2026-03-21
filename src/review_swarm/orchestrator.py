"""Orchestrator -- single-command review planning and coordination.

Takes a scope (file pattern or directory) and a task description,
then produces a complete execution plan that an LLM agent can follow.

ReviewSwarm is infrastructure, not an LLM. The orchestrator doesn't
run agents -- it creates an optimal plan and returns it. The calling
LLM follows the plan step by step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .expert_profiler import ExpertProfiler
from .session_manager import SessionManager
from .models import now_iso


@dataclass
class ReviewPlan:
    """A complete execution plan for a multi-expert code review."""

    session_id: str
    project_path: str
    scope: str
    task: str
    files: list[str]
    experts: list[dict]
    assignments: list[dict]  # {expert, files: [...]}
    phases: list[dict]       # ordered phases with instructions
    summary: str             # human-readable summary

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_path": self.project_path,
            "scope": self.scope,
            "task": self.task,
            "file_count": len(self.files),
            "expert_count": len(self.experts),
            "experts": self.experts,
            "assignments": self.assignments,
            "phases": self.phases,
            "summary": self.summary,
        }


# Map task keywords to expert preferences
_TASK_EXPERT_HINTS: dict[str, list[str]] = {
    "security": ["security-surface", "error-handling", "api-signatures"],
    "безопасност": ["security-surface", "error-handling", "api-signatures"],
    "performance": ["performance", "resource-lifecycle", "dead-code"],
    "производительност": ["performance", "resource-lifecycle", "dead-code"],
    "concurrency": ["threading-safety", "resource-lifecycle", "error-handling"],
    "многопоточност": ["threading-safety", "resource-lifecycle", "error-handling"],
    "quality": ["test-quality", "error-handling", "consistency", "dead-code"],
    "качеств": ["test-quality", "error-handling", "consistency", "dead-code"],
    "pre-release": ["security-surface", "threading-safety", "api-signatures", "error-handling", "dependency-drift"],
    "релиз": ["security-surface", "threading-safety", "api-signatures", "error-handling", "dependency-drift"],
    "full": [],  # all experts
    "полн": [],  # all experts
    "bug": ["threading-safety", "error-handling", "api-signatures", "consistency"],
    "баг": ["threading-safety", "error-handling", "api-signatures", "consistency"],
    "type": ["type-safety", "api-signatures", "consistency"],
    "тип": ["type-safety", "api-signatures", "consistency"],
    "log": ["logging-patterns", "error-handling", "security-surface"],
    "лог": ["logging-patterns", "error-handling", "security-surface"],
    "dependency": ["dependency-drift", "consistency", "dead-code"],
    "зависимост": ["dependency-drift", "consistency", "dead-code"],
    "test": ["test-quality", "consistency", "dead-code"],
    "тест": ["test-quality", "consistency", "dead-code"],
    "doc": ["project-context", "consistency", "api-signatures"],
    "документ": ["project-context", "consistency", "api-signatures"],
}

_SKIP_DIRS = {
    "node_modules", ".venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".tox", "egg-info",
}

_SOURCE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".kt", ".kts",
    ".cs", ".cpp", ".c", ".h", ".hpp",
    ".rb", ".ex", ".exs", ".swift", ".php",
}


class Orchestrator:
    """Plans and initializes a complete multi-expert review session."""

    def __init__(self, config: Config, session_manager: SessionManager,
                 expert_profiler: ExpertProfiler):
        self._config = config
        self._session_mgr = session_manager
        self._profiler = expert_profiler

    def plan_review(
        self,
        project_path: str,
        scope: str = "",
        task: str = "",
        max_experts: int = 5,
        session_name: str | None = None,
    ) -> ReviewPlan:
        """Create a complete review plan.

        Args:
            project_path: Root of the project to review.
            scope: File pattern or subdirectory (e.g., "src/", "**/*.py", "src/server.py").
                   Empty string means entire project.
            task: Description of what to focus on (e.g., "security audit",
                  "pre-release review", "check threading safety").
                  Used to select and prioritize experts.
            max_experts: Maximum number of experts to include.
            session_name: Optional session name.

        Returns:
            A ReviewPlan with session_id, file list, expert assignments,
            and phased execution instructions.
        """
        proj = Path(project_path).resolve()

        # 1. Create session
        session_id = self._session_mgr.start_session(
            str(proj), name=session_name,
        )

        # 2. Collect files matching scope
        files = self._collect_files(proj, scope)

        # 3. Select experts based on task + project analysis
        experts = self._select_experts(proj, task, files, max_experts)

        # 4. Assign files to experts (round-robin with affinity)
        assignments = self._assign_files(files, experts)

        # 5. Build phased execution plan
        phases = self._build_phases(session_id, assignments, task)

        # 6. Summary
        expert_names = [e["profile_name"] for e in experts]
        summary = (
            f"Review session {session_id} created.\n"
            f"Scope: {scope or 'entire project'} ({len(files)} files)\n"
            f"Task: {task or 'general review'}\n"
            f"Experts: {', '.join(expert_names)} ({len(experts)} experts)\n"
            f"Execute the {len(phases)} phases below in order."
        )

        return ReviewPlan(
            session_id=session_id,
            project_path=str(proj),
            scope=scope,
            task=task,
            files=files,
            experts=experts,
            assignments=assignments,
            phases=phases,
            summary=summary,
        )

    def _collect_files(self, proj: Path, scope: str) -> list[str]:
        """Collect source files matching the scope pattern."""
        files: list[str] = []

        if not proj.exists():
            return files

        # Determine base path and pattern
        if scope:
            # Check if scope is a specific file
            scope_path = proj / scope
            if scope_path.is_file():
                return [scope]

            # Check if scope is a directory
            if scope_path.is_dir():
                base = scope_path
                pattern = "**/*"
            else:
                # Treat as glob pattern
                base = proj
                pattern = scope
        else:
            base = proj
            pattern = "**/*"

        for f in base.glob(pattern):
            if not f.is_file():
                continue
            if f.suffix not in _SOURCE_EXTS:
                continue
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            try:
                rel = str(f.relative_to(proj)).replace("\\", "/")
                files.append(rel)
            except ValueError:
                continue

        files.sort()
        return files

    def _select_experts(
        self, proj: Path, task: str, files: list[str], max_experts: int,
    ) -> list[dict]:
        """Select experts based on task keywords and project analysis."""
        # Get all suggestions from profiler
        all_suggestions = self._profiler.suggest_experts(str(proj))

        # Boost experts that match task keywords
        task_lower = task.lower()
        boosted: set[str] = set()
        for keyword, expert_names in _TASK_EXPERT_HINTS.items():
            if keyword in task_lower:
                if not expert_names:  # "full" / "полн" = all experts
                    return all_suggestions[:max_experts]
                boosted.update(expert_names)

        if boosted:
            # Sort: boosted first (by original confidence), then rest
            existing_names = {s["profile_name"] for s in all_suggestions}
            boosted_list = [s for s in all_suggestions if s["profile_name"] in boosted]
            rest = [s for s in all_suggestions if s["profile_name"] not in boosted]

            # Inject task-hinted experts that weren't in suggestions
            # (e.g., security-surface for a project with no web imports)
            for name in boosted:
                if name not in existing_names:
                    try:
                        profile = self._profiler.load_profile(name)
                        boosted_list.append({
                            "profile_name": name,
                            "name": profile.get("name", name),
                            "description": profile.get("description", ""),
                            "confidence": 0.8,  # task-hinted = high confidence
                        })
                    except FileNotFoundError:
                        pass

            result = boosted_list + rest
        else:
            result = all_suggestions

        # Ensure minimum 2 experts for cross-validation
        return result[:max(max_experts, 2)]

    def _assign_files(
        self, files: list[str], experts: list[dict],
    ) -> list[dict]:
        """Assign files to experts. Each expert gets all files to review
        (they focus on their own expertise area), but we limit to avoid
        overloading a single expert on huge projects.
        """
        if not experts or not files:
            return []

        # For small projects (< 30 files): every expert reviews all files
        if len(files) <= 30:
            return [
                {
                    "expert": e["profile_name"],
                    "files": list(files),
                    "file_count": len(files),
                }
                for e in experts
            ]

        # For larger projects: distribute files across experts
        # Each file gets reviewed by at least 2 experts for cross-validation
        assignments: dict[str, list[str]] = {e["profile_name"]: [] for e in experts}

        for i, f in enumerate(files):
            # Primary expert (round-robin)
            primary = experts[i % len(experts)]["profile_name"]
            assignments[primary].append(f)

            # Secondary expert (next in rotation)
            secondary = experts[(i + 1) % len(experts)]["profile_name"]
            if secondary != primary:
                assignments[secondary].append(f)

        return [
            {
                "expert": name,
                "files": sorted(set(file_list)),
                "file_count": len(set(file_list)),
            }
            for name, file_list in assignments.items()
        ]

    def _build_phases(
        self, session_id: str, assignments: list[dict], task: str,
    ) -> list[dict]:
        """Build the phased execution plan."""
        phases = []

        # Phase 1: Review (each expert reviews their assigned files)
        review_instructions = []
        for a in assignments:
            expert = a["expert"]
            file_list = a["files"]
            review_instructions.append({
                "expert_role": expert,
                "action": "review",
                "description": (
                    f"As {expert}, review {len(file_list)} files. "
                    f"For each file: call claim_file, read the file content, "
                    f"then call post_finding for each issue found. "
                    f"Focus on: {task or 'general code quality'}."
                ),
                "files": file_list,
                "tools_to_use": ["claim_file", "post_finding", "release_file"],
            })

        phases.append({
            "phase": 1,
            "name": "Review",
            "description": (
                "Each expert reviews their assigned files and posts findings. "
                "Claim files before reviewing. Post findings with evidence "
                "(actual + expected + source_ref). Release files when done."
            ),
            "instructions": review_instructions,
        })

        # Phase 2: Cross-check (each expert reads others' findings and reacts)
        cross_check_instructions = []
        for a in assignments:
            expert = a["expert"]
            cross_check_instructions.append({
                "expert_role": expert,
                "action": "cross_check",
                "description": (
                    f"As {expert}, call get_findings to see all findings from "
                    f"other experts. For findings in your area of expertise: "
                    f"CONFIRM if you agree, DISPUTE if you disagree (explain why), "
                    f"EXTEND if you have additional context. "
                    f"Check get_inbox for questions from other experts."
                ),
                "tools_to_use": ["get_findings", "react", "get_inbox", "send_message"],
            })

        phases.append({
            "phase": 2,
            "name": "Cross-check",
            "description": (
                "Each expert reviews other experts' findings and reacts. "
                "This builds consensus: 2+ confirms = confirmed, "
                "1+ dispute = disputed. Also answer any pending queries."
            ),
            "instructions": cross_check_instructions,
        })

        # Phase 3: Report
        phases.append({
            "phase": 3,
            "name": "Report",
            "description": (
                "Generate the final review report. Call get_summary to get "
                "the aggregated report with confirmed/disputed findings. "
                "Then call end_session to close the session."
            ),
            "instructions": [{
                "action": "report",
                "description": "Call get_summary, then end_session.",
                "tools_to_use": ["get_summary", "end_session"],
            }],
        })

        return phases
