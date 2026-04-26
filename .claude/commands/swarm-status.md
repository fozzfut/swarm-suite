---
description: Show what's happening in the Swarm Suite for this project + 2-3 next-step options
---

You are operating in **Swarm Suite navigator mode** (the `swarm_suite_navigator` skill applies). The user just typed `/swarm-status` to get oriented.

Do this:

1. Call `kb_navigator_state(project_path=<the current working directory>)`.
2. Present a concise status block in plain language:
   * Current pipeline stage (or "no pipeline yet").
   * Open artifacts count (judgings / verifications / pgve / flows / debates).
   * Recent decisions (top 3 by recency).
3. Then offer the **top 2-3 suggested_next_steps** from the snapshot, formatted as a numbered menu. For each option include WHAT (in human language, not tool names), WHY (state evidence), and rough effort estimate.
4. End with: *"What would you like to do?"*

Do **not** dump the raw JSON. Do **not** list all 84 MCP tools. Translate.

If `active_pipeline` is null → suggest starting one + ask the greenfield/embedded clarifying question.

If multiple options share a kind (e.g. several "continue_artifact"), group them under one human label rather than enumerating separately.
