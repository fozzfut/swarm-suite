"""Pipeline orchestration -- defines the standard Swarm Suite workflow.

Stages:
  0. spec    -- Hardware spec analysis (SpecSwarm) [optional, for embedded projects]
  1. arch    -- Architecture analysis (ArchSwarm)
  2. review  -- Code review (ReviewSwarm)
  3. fix     -- Apply fixes (FixSwarm)
  4. verify  -- Regression check
  5. doc     -- Documentation update (DocSwarm)

Each stage requires explicit user advancement. Findings from previous
stages are available as context for later stages.
"""

import copy
import json
import logging
import os
import secrets
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("swarm_kb.pipeline")

class StageStatus:
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"

STAGE_ORDER = ["idea", "spec", "arch", "plan", "review", "fix", "verify", "doc", "harden", "release"]

STAGE_INFO = {
    "idea": {
        "name": "Idea Capture",
        "tool": "swarm-kb",
        "description": "Greenfield brainstorming. Drives the brainstorming skill: one question at a time, 2-3 design alternatives, incremental design presentation. Optional for projects that already have a design.",
        "actions": [
            "1. kb_start_idea_session(project_path, prompt) to open the session",
            "2. Drive the `brainstorming` skill: capture answers via kb_capture_idea_answer",
            "3. kb_record_alternatives(sid, alternatives, chosen_id) for Phase 2",
            "4. kb_finalize_idea_design(sid, design_md) when the user approves",
            "5. kb_advance_pipeline(pipeline_id) to enter Architecture",
        ],
        "optional": True,
    },
    "spec": {
        "name": "Hardware Spec Analysis",
        "tool": "spec-swarm",
        "description": "Analyze datasheets, register maps, and hardware documentation. Extract pin configs, protocols (CAN, SPI, I2C, EtherCAT, Modbus, etc.), timing constraints, memory layout, and power specs.",
        "actions": [
            "1. Run spec_start_session(project_path) to begin",
            "2. Run spec_ingest(session_id, document_path) for each datasheet/document",
            "3. Run spec_check_conflicts(session_id) to find pin/bus/power conflicts",
            "4. Run spec_export_for_arch(session_id) to post constraints to swarm-kb",
            "5. Review extracted specs — correct any parsing errors",
            "6. Call kb_advance_pipeline(pipeline_id) when ready for architecture analysis",
        ],
        "optional": True,
    },
    "arch": {
        "name": "Architecture Analysis",
        "tool": "arch-swarm",
        "description": "Analyze project architecture: coupling, complexity, dependencies. Run debates on design questions.",
        "actions": [
            "1. Run arch_analyze(project_path) to scan for structural issues",
            "2. Optionally run orchestrate_debate(project_path, topic) for design decisions",
            "3. Review the findings -- approve valid ones, dismiss false positives",
            "4. Call kb_advance_pipeline(pipeline_id) when ready for plan or review",
        ],
    },
    "plan": {
        "name": "Implementation Plan",
        "tool": "swarm-kb",
        "description": "Convert approved ADRs into a TDD-grade executable plan. Drives the writing_plans skill: 2-5-minute tasks, failing test first, exact commands. Optional but strongly recommended for greenfield work.",
        "actions": [
            "1. kb_start_plan_session(project_path, adr_ids) to anchor the plan to ADRs",
            "2. Drive the `writing_plans` skill: emit each task via kb_emit_task",
            "3. kb_finalize_plan(sid, plan_md) -- validates against the writing_plans contract",
            "4. Fix any validation errors and re-finalize",
            "5. kb_advance_pipeline(pipeline_id) to enter Review",
        ],
        "optional": True,
    },
    "review": {
        "name": "Code Review",
        "tool": "review-swarm",
        "description": "Multi-expert code review informed by architectural decisions.",
        "actions": [
            "1. Run orchestrate_review(project_path) — experts receive arch context automatically",
            "2. Experts review code and post findings",
            "3. Cross-check phase: experts react to each other's findings",
            "4. Review findings, confirm or dismiss",
            "5. Call kb_advance_pipeline(pipeline_id) when ready to apply fixes",
        ],
    },
    "fix": {
        "name": "Apply Fixes",
        "tool": "fix-swarm",
        "description": "Fix confirmed issues from architecture analysis and code review.",
        "actions": [
            "1. Run snapshot_tests() to save test baseline",
            "2. Start fix session from review + arch findings",
            "3. Fix experts propose fixes with consensus",
            "4. Review and approve fix proposals",
            "5. Apply approved fixes",
            "6. Run kb_check_quality_gate(findings, fixes_applied, regressions, history) after each fix iteration",
            "7. If recommendation='continue': fix more, re-review, re-check gate",
            "8. If recommendation='stop_clean': advance to verify stage",
            "9. If recommendation='stop_circuit_breaker': STOP — review manually, fix cycle is unstable",
        ],
    },
    "verify": {
        "name": "Regression Check",
        "tool": "fix-swarm",
        "description": "Verify fixes don't break anything. Quality gate confirms stability.",
        "actions": [
            "1. Run check_regression() — syntax, tests, re-scan",
            "2. Run kb_check_quality_gate(findings, fixes_applied, regressions, history) to confirm stability",
            "3. If regression: rollback and re-fix",
            "4. If clean and gate passed: call kb_advance_pipeline(pipeline_id) to advance to documentation",
        ],
    },
    "doc": {
        "name": "Documentation Update",
        "tool": "doc-swarm",
        "description": "Update documentation to reflect changes.",
        "actions": [
            "1. Run doc_verify() to find stale docs",
            "2. Run doc_generate() to update API docs",
            "3. Review generated documentation",
            "4. Call kb_advance_pipeline(pipeline_id) to complete the pipeline",
        ],
    },
}


@dataclass
class StageState:
    stage: str = ""
    status: str = StageStatus.PENDING
    started_at: str = ""
    completed_at: str = ""
    session_ids: list[str] = field(default_factory=list)  # tool session IDs for this stage
    approved_findings: int = 0
    dismissed_findings: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "session_ids": self.session_ids,
            "approved_findings": self.approved_findings,
            "dismissed_findings": self.dismissed_findings,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StageState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Pipeline:
    id: str = ""
    project_path: str = ""
    created_at: str = ""
    current_stage: str = ""  # auto-set to STAGE_ORDER[0] in __post_init__
    stages: dict[str, StageState] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = "pipe-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.stages:
            for stage in STAGE_ORDER:
                self.stages[stage] = StageState(stage=stage)
            # Default: start at the first stage in STAGE_ORDER. Callers that
            # want to skip earlier optional stages (e.g. an existing project
            # that doesn't need ideation) call `skip_to(...)` after start.
            first = STAGE_ORDER[0]
            self.stages[first].status = StageStatus.ACTIVE
            self.stages[first].started_at = self.created_at
            self.current_stage = first

    def get_current(self) -> StageState:
        return self.stages[self.current_stage]

    def advance(self, notes: str = "") -> str | None:
        """Advance to next stage. Returns new stage name or None if completed."""
        current = self.stages[self.current_stage]
        current.status = StageStatus.COMPLETED
        current.completed_at = datetime.now(timezone.utc).isoformat()
        if notes:
            current.notes = notes

        idx = STAGE_ORDER.index(self.current_stage)
        if idx + 1 >= len(STAGE_ORDER):
            return None  # pipeline completed

        next_stage = STAGE_ORDER[idx + 1]
        self.current_stage = next_stage
        self.stages[next_stage].status = StageStatus.ACTIVE
        self.stages[next_stage].started_at = datetime.now(timezone.utc).isoformat()
        return next_stage

    def rewind_to(self, stage: str, reason: str = "") -> bool:
        """Go BACKWARD to an earlier stage.

        The current stage and any newer stages are reset to PENDING (their
        history -- session_ids, approved/dismissed counts -- is preserved
        for audit). The target stage becomes ACTIVE. The `reason` is
        appended to the target stage's notes so the rewind shows up in
        pipeline status / log.

        Returns True if rewind succeeded; False if `stage` is invalid or
        is not strictly earlier than the current stage.

        Use case: discoveries during Review (stage 3) reveal that an ADR
        from Architecture (stage 1) is wrong -> rewind_to("arch") to
        re-debate, then advance forward through Review again.
        """
        if stage not in STAGE_ORDER:
            return False
        target_idx = STAGE_ORDER.index(stage)
        current_idx = STAGE_ORDER.index(self.current_stage)
        if target_idx >= current_idx:
            return False  # rewind must go strictly backward

        now = datetime.now(timezone.utc).isoformat()
        # Reset target stage and everything between target and current to PENDING
        for i in range(target_idx, current_idx + 1):
            s = STAGE_ORDER[i]
            self.stages[s].status = StageStatus.PENDING
            self.stages[s].started_at = ""
            self.stages[s].completed_at = ""
        # Activate the target
        self.stages[stage].status = StageStatus.ACTIVE
        self.stages[stage].started_at = now
        prefix = f"[rewound from {self.current_stage}@{now}] "
        if reason:
            existing = self.stages[stage].notes
            self.stages[stage].notes = (prefix + reason + ("\n" + existing if existing else ""))
        self.current_stage = stage
        return True

    def skip_to(self, stage: str) -> bool:
        """Skip intermediate stages and jump to a specific stage (forward only).

        For backward navigation, use `rewind_to`.
        """
        if stage not in STAGE_ORDER:
            return False
        target_idx = STAGE_ORDER.index(stage)
        current_idx = STAGE_ORDER.index(self.current_stage)
        if target_idx <= current_idx:
            return False  # cannot go backward

        # Mark skipped stages
        for i in range(current_idx, target_idx):
            s = STAGE_ORDER[i]
            if self.stages[s].status == StageStatus.ACTIVE:
                self.stages[s].status = StageStatus.SKIPPED
                self.stages[s].completed_at = datetime.now(timezone.utc).isoformat()

        self.current_stage = stage
        self.stages[stage].status = StageStatus.ACTIVE
        self.stages[stage].started_at = datetime.now(timezone.utc).isoformat()
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_path": self.project_path,
            "created_at": self.created_at,
            "current_stage": self.current_stage,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pipeline":
        stages = {}
        for k, v in d.get("stages", {}).items():
            stages[k] = StageState.from_dict(v)
        return cls(
            id=d.get("id", ""),
            project_path=d.get("project_path", ""),
            created_at=d.get("created_at", ""),
            current_stage=d.get("current_stage", STAGE_ORDER[0]),
            stages=stages,
        )


class PipelineManager:
    """Manages pipeline lifecycle with file persistence."""

    def __init__(self, pipelines_dir: Path):
        self._dir = pipelines_dir
        self._pipelines: dict[str, Pipeline] = {}
        self._lock = threading.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    def start(self, project_path: str) -> Pipeline:
        """Start a new pipeline for a project."""
        with self._lock:
            pipe = Pipeline(project_path=project_path)
            self._pipelines[pipe.id] = pipe
            self._save(pipe.id)
            return pipe

    def get(self, pipeline_id: str) -> Pipeline | None:
        with self._lock:
            return copy.deepcopy(self._pipelines.get(pipeline_id))

    def list_all(self) -> list[Pipeline]:
        with self._lock:
            return [copy.deepcopy(p) for p in self._pipelines.values()]

    def advance(self, pipeline_id: str, notes: str = "") -> dict:
        """Advance pipeline to next stage (user gate)."""
        with self._lock:
            pipe = self._pipelines.get(pipeline_id)
            if not pipe:
                return {"error": f"Pipeline {pipeline_id} not found"}

            next_stage = pipe.advance(notes)
            self._save(pipe.id)

            if next_stage is None:
                return {"status": "completed", "message": "Pipeline completed all stages"}

            info = STAGE_INFO[next_stage]
            return {
                "status": "advanced",
                "current_stage": next_stage,
                "stage_name": info["name"],
                "tool": info["tool"],
                "description": info["description"],
                "actions": info["actions"],
                "pipeline": pipe.to_dict(),
            }

    def rewind(self, pipeline_id: str, stage: str, reason: str = "") -> dict:
        """Rewind a pipeline to an earlier stage. See Pipeline.rewind_to."""
        with self._lock:
            pipe = self._pipelines.get(pipeline_id)
            if not pipe:
                return {"error": f"Pipeline {pipeline_id} not found"}
            if not pipe.rewind_to(stage, reason=reason):
                return {"error": f"Cannot rewind to {stage!r} (must be earlier than current)"}
            self._save(pipe.id)
            info = STAGE_INFO[stage]
            return {
                "status": "rewound",
                "current_stage": stage,
                "stage_name": info["name"],
                "reason": reason,
                "actions": info["actions"],
                "pipeline": pipe.to_dict(),
            }

    def skip_to(self, pipeline_id: str, stage: str) -> dict:
        """Skip to a specific stage (forward only). For backward, use rewind()."""
        with self._lock:
            pipe = self._pipelines.get(pipeline_id)
            if not pipe:
                return {"error": f"Pipeline {pipeline_id} not found"}
            if not pipe.skip_to(stage):
                return {"error": f"Invalid stage: {stage}"}
            self._save(pipe.id)
            info = STAGE_INFO[stage]
            return {
                "status": "skipped_to",
                "current_stage": stage,
                "stage_name": info["name"],
                "actions": info["actions"],
                "pipeline": pipe.to_dict(),
            }

    def update_stage_stats(self, pipeline_id: str, session_id: str = "",
                           approved: int = 0, dismissed: int = 0) -> dict:
        """Update current stage statistics."""
        with self._lock:
            pipe = self._pipelines.get(pipeline_id)
            if not pipe:
                return {"error": f"Pipeline {pipeline_id} not found"}
            current = pipe.get_current()
            if session_id and session_id not in current.session_ids:
                current.session_ids.append(session_id)
            current.approved_findings += approved
            current.dismissed_findings += dismissed
            self._save(pipe.id)
            return current.to_dict()

    def _save(self, pipeline_id: str) -> None:
        pipe = self._pipelines[pipeline_id]
        path = self._dir / f"{pipeline_id}.json"
        content = json.dumps(pipe.to_dict(), indent=2)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
            with fh:
                fh.write(content)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_all(self) -> None:
        for f in self._dir.glob("pipe-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                pipe = Pipeline.from_dict(data)
                self._pipelines[pipe.id] = pipe
            except Exception as exc:
                _log.warning("Failed to load pipeline %s: %s", f, exc)
