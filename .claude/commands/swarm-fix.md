---
description: Apply fixes for confirmed findings (uses PGVE for ones likely to need iteration)
---

You are in **Swarm Suite navigator mode**. The user typed `/swarm-fix $ARGUMENTS`. The `$ARGUMENTS` (if any) names a specific finding ID; if empty, work through all confirmed findings in priority order.

Do this:

1. Call `kb_navigator_state(project_path=<cwd>)`.
2. Pipeline check: if not in `fix` stage, tell the user and ask whether to advance.
3. Find candidates:
   * If `$ARGUMENTS` is a finding ID: that's the target.
   * Else: `kb_search_findings(severity=high, status=confirmed) + (medium, confirmed)`. Sort by severity DESC, then by confidence DESC.
4. Show the user the prioritised list (max 5 entries) and confirm: "Fix all of these, or pick a subset?"
5. For each finding to fix:
   a. **Snapshot tests once** at the start: `snapshot_tests(session_id)`.
   b. Open or reuse a fix session: `start_session(review_session=..., arch_session=...)`.
   c. **Decide PGVE vs one-shot**: if the finding is in `security` / `threading-safety` / `error-handling` (high-iteration-risk categories), drive PGVE -- `kb_start_pgve(task_spec=<concise description>)` then submit_candidate / evaluate_candidate cycle until accepted or budget exhausted. Otherwise just `propose_fix` once.
   d. Always **show the proposed diff to the user before apply**. Never silently `apply_approved`.
   e. After the user approves: `apply_approved(...)` for the consensus fix, or `apply_single(...)` for an individual one.
   f. After each fix iteration: `kb_check_quality_gate(...)`. Surface the recommendation:
      * `continue` -- offer next finding.
      * `stop_clean` -- offer to advance to verify stage.
      * `stop_circuit_breaker` -- STOP, tell user the cycle is unstable and recommend manual review.
6. Once done, end with: "Fixes applied -- want to run verify next?"

Anti-patterns to avoid:
* Applying any fix without showing the diff first.
* Calling `apply_approved` if `kb_check_quality_gate` last returned `stop_circuit_breaker` -- escalate to user.
* Looping forever on the same finding -- PGVE has a hard budget (default 5 candidates); respect it.
