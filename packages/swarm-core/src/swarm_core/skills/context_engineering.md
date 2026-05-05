---
name: Context Engineering
slug: context_engineering
when_to_use: always — managing what enters the AI's context window is the single biggest lever on output quality
version: 1.0.0
universal: true
attribution: "Inspired by addyosmani/agent-skills (skills/context-engineering/SKILL.md). Re-authored for the Swarm Suite."
---

# Context Engineering (apply to every task)

## Overview

Context is the most important variable in AI-agent output quality. The same model with bad context produces bad answers; with good context it produces good ones. Treat context like a budget: every token spent on irrelevant material is a token unavailable for reasoning.

**Core principle:** more context is not better — *relevant* context is better. Lean, well-targeted prompts beat exhaustive ones.

## When to Use

Always. Every reasoning step has an implicit context-engineering decision: what to load, what to summarize, what to drop, what to keep verbatim.

**This skill matters most when:**
- The task spans multiple files / packages and you can't load all of them
- A long pipeline (idea → spec → arch → code → review → fix) accumulates intermediate artefacts
- The user asks for changes in a domain that has both behavioural rules (CLAUDE.md) and reference material (datasheets, specs)
- A previous attempt failed and you're re-running with more context — pause and ask whether *more* is actually the right move

## The Context Hierarchy

Load context in this order, stop when the task is answerable:

1. **Persistent rules** — project CLAUDE.md, persona system prompt, this skill body, universal skills (`solid_dry`, `karpathy_guidelines`). These are always-on.
2. **Specifications & decisions** — relevant entries from spec-swarm (registers, pins, protocols, timing) and `kb_get_decisions` for ADRs that constrain the answer. Pull only what the task touches.
3. **Source files** — the specific files the task modifies. **Read whole files**, not snippets, when the file is under ~600 LOC; otherwise use targeted reads with line offsets.
4. **Reference material** — datasheets, related-project READMEs, third-party API docs. Pull only the section relevant to the task.
5. **Conversation history** — the prior turns. The most recent turn is most relevant; older turns lose value fast unless the user explicitly references them.

If you've completed level N and the answer is clear, stop. Don't pre-load level N+1 "in case it's needed".

## Strategies

**Targeted retrieval over brain-dump.** Prefer `kb_semantic_search` / `kb_search_findings` / `kb_get_decisions` with filters over reading whole JSONL files. Vector search returns top-K by relevance; full reads waste tokens on the long tail.

**Hierarchical summarisation.** When something *must* be in context but is long (large code map, multi-page datasheet section), summarise it in 5–15 lines and link to the source for drill-down. The agent sees the summary by default; the source is one tool-call away if needed.

**Just-in-time loading.** Don't pre-load files for hypothetical follow-ups. Load when the question requires it. Each load is cheap; an over-stuffed context isn't.

**Cite, don't paraphrase, when precision matters.** For datasheet timing, register addresses, protocol bytes — quote the source verbatim with file/line. Paraphrasing hardware facts introduces drift.

## Confusion Management

When you notice your reasoning is going in circles:

- **Output what you currently know.** Force yourself to write down the assumptions in plain language. Often the gap reveals itself.
- **Ask for the missing piece** rather than guessing. "I need to know X to answer; should I read Y, or do you have it?" beats inventing X.
- **Drop and reload.** If the conversation has accumulated stale context (failed attempts, abandoned approaches), explicitly drop them: "Setting aside the earlier draft, here's a fresh attempt based on the latest constraint."

## Anti-Patterns

| Anti-pattern | Problem | Fix |
|---|---|---|
| "Let me read all files in the package first" | 80% of tokens go to irrelevant files | Load files the task touches; expand on demand |
| "I'll include the full datasheet in case anything's relevant" | Datasheet drowns out actual question | Cite the specific section; offer to load more |
| "I keep adding context every turn" | Context grows unboundedly; older turns become noise | Periodically summarise and reset |
| Re-reading the same file every turn | Wastes tokens; the file's already known | Trust prior reads unless the file changed |
| Loading prior debate transcripts to "remind" the agent | Re-running the debate burns tokens | Reference the resulting ADR id (`adr-xyz`) |

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "More context can't hurt" | It can — relevant signal drowns in noise, the agent latches on to the wrong constraint |
| "I'll load it now in case I need it later" | Tokens spent now are unavailable later; load on demand |
| "The user expects me to know everything" | The user expects correct answers, not exhaustive reading; ask when unsure |
| "Re-summarising costs more tokens than just keeping the original" | False at scale: summarising once and keeping the summary is cheaper than carrying the original through every subsequent turn |

## Red Flags

- Context window is 80% full and you haven't started reasoning yet
- Re-reading the same file in successive turns
- Quoting long passages and never referring to them again
- Adding context on every retry instead of changing approach
- Carrying multi-turn conversation noise (failed attempts, abandoned ideas)

## Verification

Before responding, check:

- [ ] Every file/section you loaded was *used* in the answer
- [ ] Specs and ADRs cited in the response are real (paths exist, IDs resolve)
- [ ] Quotations are verbatim (especially register addresses, timing values)
- [ ] Older conversation turns that are no longer load-bearing have been allowed to drift out, not actively re-introduced
