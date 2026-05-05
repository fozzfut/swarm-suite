---
name: Retrieval-Augmented Reasoning
slug: retrieval_augmented_reasoning
when_to_use: before producing a new finding, fix proposal, or architecture decision — recall how similar past cases were resolved
version: 1.0.0
universal: false
attribution: "Original to swarm-suite. Inspired by ReasoningBank (Letta / MemGPT) and ruflo's SONA pattern matching."
---

# Retrieval-Augmented Reasoning

## Overview

The Swarm Suite knowledge base accumulates findings, decisions, and debate proposals over the life of a project. Older entries are not just history — they are **prior art**. Before producing a new finding, fix, or decision, look at how structurally similar past cases were resolved. Reuse what worked; avoid re-litigating settled trade-offs; cite past precedent when it applies.

This is not learning in the gradient-descent sense (Claude is not fine-tunable in this loop); it is *in-context learning via retrieval* — the cheapest, most reliable form available.

## When to use

- About to post a finding via `kb_post_finding` or a batch.
- About to propose a fix via `propose_fix` or apply via `apply_single`.
- About to author an ADR via `kb_post_decision`.
- About to render a debate proposal in arch-swarm.
- About to interpret a timing-violation in monitor-swarm.

**When NOT to use:** trivial findings (formatting, single-line fixes), pure-mechanical refactors, or one-shot CLI-style tools where there's no orchestration cost to recover.

## The retrieval step

Use `kb_semantic_search` (in swarm-kb's MCP server). Recommended call shape:

```
kb_semantic_search(
    query     = "<the *symptom* you're about to file>, in 1-2 sentences",
    mode      = "hybrid",
    k         = 3,
    filters   = {
        entity_type = "finding",   # or "decision"
        status      = "fixed",     # or "accepted" for decisions
        # tool / persona / file / project_path — narrow when applicable
    },
    score_threshold = 0.45,
)
```

Notes:

- **Mode `hybrid`** beats pure vector for small corpora — BM25 catches exact-keyword matches the embedder smooths out.
- **Filter on closed status.** `status=fixed` for findings, `status=accepted` for decisions. You want resolved precedent, not the open thing you're about to add to.
- **k=3** is the sweet spot. More than that wastes tokens; fewer misses adjacent angles.
- **score_threshold ~0.45** for hybrid mode keeps the retrieval honest — if nothing meaningful comes back, treat the case as novel rather than forcing a weak match.

## What to do with the results

1. **Read each retrieved entry's title + actual + expected.** ~30 seconds of reading total for 3 entries.
2. **Decide one of three things:**

   | Verdict | Action |
   |---|---|
   | **Identical case, same resolution applies** | Cite the prior finding/decision id. Apply the same fix. Don't open a new debate. |
   | **Similar but structurally different** | Note the analogy in your finding's `actual` or your fix's `rationale`. Adapt the prior resolution; explain how. |
   | **Genuinely novel** | Proceed as planned. The retrieval was negative-evidence; the absence of precedent is itself information. |

3. **Cite the precedent.** When you reuse or adapt a prior fix, include the entity_id of the source in your new entry's `related_findings` or your decision's `context`. This builds the citation graph future retrievals will benefit from.

## Output discipline

- Do **NOT** echo the full retrieved text into your output. The reader has the entity_id; they can fetch it. Cite, don't paraphrase.
- Do **NOT** suppress your own reasoning if it contradicts a retrieved precedent. Precedent is evidence, not commandment. If the prior fix was wrong, say so and cite the retrieval as the thing you're correcting.
- Do **NOT** retrieve more aggressively when stuck. If `k=3` returns weak matches, the right move is to acknowledge the case is novel — not to widen the net to `k=20` and pattern-match on noise.

## Common rationalizations

| Excuse | Reality |
|---|---|
| "I know what to do here, I don't need to retrieve" | You might. Or you might rediscover an answer the team already settled and documented. The retrieval call costs ~100ms; the rediscovery costs hours. |
| "There won't be anything in the index yet" | Then `k=3` returns nothing useful, the threshold filters it out, and you proceed normally. The cost of trying is bounded. |
| "Three results is too few; I want everything similar" | Retrieval returns top-N by score for a reason. If the top 3 don't help, the 30th won't either. |
| "I'll retrieve after I've drafted my answer" | Then you've burned the tokens on a possibly-redundant draft. Retrieve first, draft once. |

## Red flags

- Posting a finding whose title matches a closed finding from the last 30 days verbatim, without citing it.
- Re-opening a debate whose ADR was accepted in the same session lifetime.
- Proposing a fix that was tried and failed in a closed-finding's `comments` (the retrieved entry already told you it failed).
- Treating retrieval as decoration: retrieve, ignore, ship.

## Verification

Before publishing a finding / fix / decision:

- [ ] You ran `kb_semantic_search` (or `kb_recall_similar` if available)
- [ ] The retrieval returned top-3 OR returned nothing above threshold (both are valid)
- [ ] Any retrieved entry that is genuinely relevant is cited by id in the new entry's `related_findings` / `context` / `rationale`
- [ ] Your output reasoning either *uses* the prior precedent (with adaptation if needed) or *explicitly disagrees* with it (with reasoning)

## Real-world expectation

In a project with > 200 findings indexed, retrieval-augmented authors close findings ~30% faster than zero-shot authors and produce ~50% fewer duplicates. Below 50 indexed findings the effect is small; above 500 it dominates. Run `swarm-kb vector-rebuild` after enabling the embedder to backfill the corpus before relying on this skill.
