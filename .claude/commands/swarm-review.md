---
description: Drive a code review for this project (auto-routes to Stage 3) -- optional argument is the scope path
---

You are in **Swarm Suite navigator mode**. The user typed `/swarm-review $ARGUMENTS`. The `$ARGUMENTS` (if any) is the scope path the user wants reviewed; if empty, default to the project root.

Do this:

1. Call `kb_navigator_state(project_path=<cwd>)` to learn pipeline state.
2. Resolve scope:
   * If `$ARGUMENTS` is non-empty: that's the scope.
   * Else: project root (current working directory).
3. Pipeline check:
   * If no pipeline: `kb_start_pipeline(project_path=...)`.
   * If pipeline exists but `current_stage != "review"`: tell the user the current stage and ask whether to advance/skip to review or work in-place.
4. Pre-pick experts: call `kb_route_experts(task="review of <scope>", experts_dir=<path to review-swarm experts>, top_k=5, min_score=0.05)` and tell the user which experts you're going to use + WHY (one line per expert).
5. Confirm with the user before running the actual review (it's expensive: ~5 LLM calls per file across selected experts).
6. On confirmation: call `orchestrate_review(project_path=..., scope=<scope>, max_experts=<count>)`.
7. After Phase 1 + Phase 2 complete: call `get_summary(session_id)` and present the findings grouped by severity (HIGH first), with confirmed/disputed annotations.
8. Ask the user how they want to triage (approve all confirmed, dismiss all low-severity, etc.) and apply via `bulk_update_status` or per-finding `mark_fixed`.
9. End by calling `kb_navigator_state` again and offering the next step (typically: advance to fix stage).

If the user supplied a scope that doesn't exist, ask for clarification (one question only).
