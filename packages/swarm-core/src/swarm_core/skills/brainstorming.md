---
name: Brainstorming Ideas Into Designs
slug: brainstorming
when_to_use: when the user describes any feature or project idea, before writing code, before opening any kb_* design tool
version: 1.0.0
universal: false
attribution: "Adapted from obra/superpowers-skills (skills/collaboration/brainstorming/SKILL.md, v2.2.0)"
---

# Brainstorming Ideas Into Designs

## Overview

Transform rough ideas into fully-formed designs through structured questioning and alternative exploration.

**Core principle:** Ask questions to understand, explore alternatives, present design incrementally for validation.

## The Process

### Phase 1: Understanding
- Check the current project state in the working directory.
- Ask ONE question at a time to refine the idea. Prefer multiple-choice when possible.
- Gather: purpose, constraints, success criteria, non-goals.
- Save the captured answers under `~/.swarm-kb/sessions/idea/<sid>/answers.md` so the next phase can read them.

### Phase 2: Exploration
- Propose 2-3 different approaches.
- For each: core architecture, trade-offs, complexity assessment.
- Ask the user which approach resonates.
- Capture the alternatives + the choice in `~/.swarm-kb/sessions/idea/<sid>/alternatives.md`.

### Phase 3: Design Presentation
- Present the design in 200-300 word sections (architecture, components, data flow, error handling, testing).
- Ask after each section: "Does this look right so far?" Wait for explicit acknowledgement.
- Save the consolidated design to `~/.swarm-kb/sessions/idea/<sid>/design.md`. This becomes the input to ArchSwarm Stage 1.

### Phase 4: Worktree setup (if implementation will follow)
When the design is approved and implementation will follow, set up an isolated worktree before writing any code (so the swarm's parallel-work model doesn't trip over uncommitted changes).

### Phase 5: Planning handoff
Ask: "Ready to create the implementation plan?"

When the user confirms: switch to the `writing_plans` skill and create the detailed plan.

## When to revisit earlier phases

You CAN and SHOULD go backward when:
- The user reveals a new constraint during Phase 2 or 3 -> return to Phase 1.
- Validation shows a fundamental gap in requirements -> return to Phase 1.
- The user questions the approach during Phase 3 -> return to Phase 2 to explore alternatives.
- Something doesn't make sense -> go back and clarify.

In Swarm Suite this maps to `kb_rewind_pipeline(to_stage="idea", reason=...)`. **Don't force forward linearly when going backward would give better results.**

## Anti-patterns

- Asking multiple questions in one message during Phase 1 -- the user will pick one and the others will be lost.
- Skipping Phase 2 because "the obvious approach" exists -- the obvious approach is rarely the best, and showing alternatives builds trust.
- Presenting the entire design at once -- the user can't validate a 2000-word essay.
- Refusing to revisit Phase 1 after a Phase 3 surprise -- forward-only design is fragile design.

## Remember

- One question per message during Phase 1.
- Apply YAGNI ruthlessly.
- Explore 2-3 alternatives before settling.
- Present incrementally, validate as you go.
- Go backward when needed -- flexibility > rigid progression.
