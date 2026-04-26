---
name: Self Review Before Posting
slug: self_review
when_to_use: before publishing any finding, proposal, decision, or plan to the shared KB
version: 1.0.0
universal: false
attribution: "Original to swarm-suite; pattern inspired by obra/superpowers-skills"
---

# Self Review Before Posting

## Overview

Cross-checking between agents (`react / confirm / dispute / extend`) catches problems
*after* they enter the KB. By then a partner agent has already read the finding,
maybe acted on it. Self-review catches the same problems *before* publication --
cheaper, faster, less polluted timeline.

**Core principle:** before you call `post_finding`, `propose_fix`, `kb_post_decision`,
or any other publish-shaped tool, run the checklist below against your own draft.
If any check fails, fix the draft or downgrade the severity.

## When to use

Always. Every expert. Every publish.

This skill is intentionally cheap. The full checklist is 30 seconds of reasoning;
the cost of a bad finding propagating through the swarm is much higher (other
agents react, fix-swarm proposes a fix to a non-existent bug, regression test
gets weakened to silence the false positive).

## The Checklist

For each item: answer **out loud** before publishing. "I think so" is not an answer.

### For findings (`post_finding`)

1. **Source-traced.** Did I trace the input that produces the bad behavior to its
   actual source, or am I assuming the source from a heuristic? If assumed,
   downgrade `confidence` to <= 0.5 or convert to `category: investigate`.
2. **Existing-mitigation-checked.** Did I look for upstream sanitization,
   middleware, decorators, or wrapper functions that already handle this case?
   Re-read the imports. If unsure, mark `actual:` with "no upstream sanitization
   found in <files I checked>".
3. **Application-context-correct.** Is this finding actually applicable to this
   project type? (path-traversal in a desktop app with no untrusted input is
   FALSE; SQL injection in a SQLite-backed CLI is real but lower severity.)
4. **Evidence-shaped.** Does my finding fill `actual:`, `expected:`, AND
   `source_ref:` with concrete values from the code -- not paraphrase? If `actual:`
   is "looks unsafe" or `expected:` is "should be safe", REWRITE.
5. **Severity-calibrated.** Does my severity match my own confidence? CRITICAL
   without a confirmed exploit path is wrong -- HIGH at best, MEDIUM with
   `category: investigate` more honest.
6. **Duplicate-checked.** Did I run `find_duplicates` against active findings
   before posting? Reposting the same issue clogs the swarm.

### For fix proposals (`propose_fix`)

1. **Root-cause-fix.** Does this fix the cause or the symptom? If symptom,
   STOP -- apply `systematic_debugging` skill first.
2. **No-bundling.** Does this patch do exactly one thing? "While I'm here"
   refactors are forbidden in the same proposal -- they make consensus harder
   and bisect impossible.
3. **Towards-SOLID-DRY.** Does this fix move the codebase toward SOLID+DRY,
   or does it suppress the finding by adding a god method / branch / hard-coded
   special case? If the latter, REJECT your own proposal.
4. **Test-firstness.** Did I write a failing test that proves the bug exists
   BEFORE the fix? If no, the fix is unverifiable.
5. **Reversibility.** If this patch is wrong, can it be reverted with a single
   `git revert`? If the patch reaches into 5 files, split it.

### For ADRs (`kb_post_decision`)

1. **Trade-off-named.** Does the ADR name what was traded against what? An
   ADR without a "Why this and not X" section is a wish, not a decision.
2. **Reversibility-noted.** Is the decision reversible? If not, that should be
   the loudest sentence in the ADR.
3. **SOLID/DRY-grounded.** Which SOLID principle motivates the choice? If the
   answer is "none", the decision is taste, not architecture.

### For plans (`kb_emit_task`)

1. **2-5-minute-granularity.** Each task takes 2-5 minutes? If a task is "implement
   the auth module", it's too coarse -- split.
2. **Failing-test-first.** Does each task start with a failing test before
   implementation? If no, see `writing_plans` skill.
3. **Exact-paths.** Are all file paths absolute / repo-relative, no "appropriate
   location" hand-waving?

## Red Flags -- skip self-review and you'll regret it

- "I'm sure this is right, no need to check." -- the moment of certainty is
  precisely when self-review catches the most.
- "I'm in a hurry, the swarm will catch it." -- the swarm is more expensive than
  you. Spend 30s now to save 5min of cross-check + revert later.
- "This finding is obvious." -- obvious findings are obvious to other experts
  too; they'll mark it duplicate. Run `find_duplicates` first.
- "I don't have evidence yet but I'll add it later." -- post nothing, gather
  evidence, then post once.

## Real-world impact

False-positive findings cost the swarm in three ways: (a) other experts react,
(b) fix-swarm proposes a fix to a non-existent bug, (c) the user loses trust in
the suite. A 30-second self-review eliminates the majority of false positives
before they enter the timeline.
