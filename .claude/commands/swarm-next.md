---
description: Pick + execute the most-recommended next action in the Swarm Suite pipeline
---

You are in **Swarm Suite navigator mode**. The user typed `/swarm-next` because they want you to **just do** the next sensible step rather than ask them to choose.

Do this:

1. Call `kb_navigator_state(project_path=<cwd>)`.
2. Pick the **single highest-priority** next action from `suggested_next_steps`. Priority order:
   * `continue_artifact` (anything open and in-flight) wins -- never start something new while a session is mid-flight unless the user explicitly redirects.
   * If no in-flight artifact: pick the first `stage_continue` for the current stage.
   * If the stage's main work is done: pick `advance` (and confirm with user before destructive `kb_advance_pipeline`).
3. Tell the user **what you're about to do and why** (one sentence each).
4. Confirm with user IF the action is destructive (write to user code, finalise an artifact, advance the pipeline). For all read/scoped tool calls, just do it.
5. Execute the tool calls from the picked option's `tools` list, in order, surfacing intermediate results as you go.
6. After completion, call `kb_navigator_state` again and tell the user what's next ("done -- next step would be X; want to continue?").

Never ask "which would you like" -- this command means "pick one and run with it." If the user wanted to choose, they'd have used `/swarm-status`.
