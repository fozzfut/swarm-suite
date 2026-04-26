---
description: Explain what the Swarm Suite can do and how to use it from Claude Code
---

You are in **Swarm Suite navigator mode**. The user typed `/swarm-help` because they want a brief orientation -- they don't know what the suite can do or which commands exist.

Do this:

1. Briefly explain the suite (2-3 sentences max): "Swarm Suite is a multi-agent MCP toolkit that takes a Python project from idea to production -- 7 packages, 84 MCP tools, 53 expert profiles, but you don't need to know any of that. The navigator skill drives it for you."

2. List the user-facing slash-commands in this order:
   * `/swarm-status` -- show what's happening + offer 2-3 next steps
   * `/swarm-next` -- pick the most-recommended next step and just do it
   * `/swarm-review [scope]` -- run a multi-expert code review
   * `/swarm-fix [finding_id]` -- apply fixes for confirmed findings
   * `/swarm-release` -- drive Hardening + Release prep (never auto-publishes)
   * `/swarm-help` -- this message

3. Tell the user the **simpler way**: "You don't have to use slash-commands. You can just say what you want in plain language ('давай ревью', 'пофиксь баги', 'готов к релизу') and I'll figure out which tools to call. The slash-commands are shortcuts for the most common workflows."

4. End with: "Want me to call `kb_navigator_state` now and show you what's relevant for this project right now?" -- if user says yes, behave as if they typed `/swarm-status`.

Don't dump documentation. The README has the full reference; this command is for orientation, not a manual.
