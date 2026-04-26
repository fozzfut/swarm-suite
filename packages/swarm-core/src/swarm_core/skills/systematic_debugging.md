---
name: Systematic Debugging
slug: systematic_debugging
when_to_use: when encountering any bug, test failure, or unexpected behavior, before proposing fixes
version: 1.0.0
universal: false
attribution: "Adapted from obra/superpowers-skills (skills/debugging/systematic-debugging/SKILL.md, v2.1.0)"
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue: test failures, production bugs, unexpected behavior, performance problems, build failures, integration issues.

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- The user wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

BEFORE attempting ANY fix:

1. **Read error messages carefully.** Don't skip past errors or warnings -- they often contain the exact solution. Read stack traces completely. Note line numbers, file paths, error codes.
2. **Reproduce consistently.** Can you trigger it reliably? What are the exact steps? Does it happen every time? If not reproducible -> gather more data, don't guess.
3. **Check recent changes.** What changed that could cause this? Git diff, recent commits, new dependencies, config changes, environmental differences.
4. **Gather evidence in multi-component systems.** When the system has multiple components (CI -> build -> signing, API -> service -> database), add diagnostic instrumentation at each component boundary BEFORE proposing fixes. Log what enters and exits each component, verify environment / config propagation, check state at each layer. Run once to see WHERE it breaks; then investigate that specific component.
5. **Trace data flow backward.** Where does the bad value originate? What called this with the bad value? Keep tracing up until you find the source. Fix at the source, not at the symptom.

### Phase 2: Pattern Analysis

Find the pattern before fixing:

1. **Find working examples.** Locate similar working code in the same codebase. What works that's similar to what's broken?
2. **Compare against references.** If implementing a known pattern, read the reference implementation COMPLETELY. Don't skim.
3. **Identify differences.** What's different between working and broken? List every difference, however small. Don't assume "that can't matter".
4. **Understand dependencies.** What other components does this need? What settings, config, environment? What assumptions does it make?

### Phase 3: Hypothesis and Testing

Scientific method:

1. **Form a single hypothesis.** State clearly: "I think X is the root cause because Y." Write it down. Be specific, not vague.
2. **Test minimally.** Make the SMALLEST possible change to test the hypothesis. One variable at a time.
3. **Verify before continuing.** Did it work? Yes -> Phase 4. Didn't work? Form a NEW hypothesis. DON'T add more fixes on top.
4. **When you don't know, say so.** Don't pretend. Ask. Research more.

### Phase 4: Implementation

Fix the root cause, not the symptom:

1. **Create a failing test case.** Simplest possible reproduction. Automated test if possible. MUST exist before fixing.
2. **Implement a single fix.** Address the root cause identified. ONE change at a time. No "while I'm here" improvements. No bundled refactoring.
3. **Verify the fix.** Test passes? No other tests broken? Issue actually resolved?
4. **If the fix doesn't work:** STOP. Count: how many fixes have you tried? If < 3, return to Phase 1 and re-analyze with the new information. **If >= 3, STOP and question the architecture (step 5).**
5. **If 3+ fixes failed: question the architecture.** Pattern indicating an architectural problem: each fix reveals new shared state / coupling / problem in a different place; fixes require massive refactoring; each fix creates new symptoms elsewhere. STOP and surface this for human review (in this suite: post a finding with `category: design`, `tags: ["arch-review-needed"]`, and set the related fix-proposal status to ARCH_REVIEW_NEEDED). DON'T attempt fix #4.

## Red Flags -- STOP and follow process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- Proposing solutions before tracing data flow
- "One more fix attempt" (when already tried 2+)
- Each fix reveals a new problem in a different place

ALL of these mean: STOP. Return to Phase 1.

## User signals you're doing it wrong

Watch for these phrases from the user -- they mean your approach isn't working:
- "Is that not happening?" -- you assumed without verifying
- "Will it show us...?" -- you should have added evidence gathering
- "Stop guessing" -- you're proposing fixes without understanding
- "Ultrathink this" -- question fundamentals, not just symptoms
- "We're stuck" (frustrated) -- your approach isn't working

When you see these: STOP. Return to Phase 1.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write the test after confirming the fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms != understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question pattern, don't fix again. |

## Quick Reference

| Phase | Key activities | Success criteria |
|-------|----------------|------------------|
| 1. Root Cause | Read errors, reproduce, check changes, gather evidence | Understand WHAT and WHY |
| 2. Pattern | Find working examples, compare | Identify differences |
| 3. Hypothesis | Form theory, test minimally | Confirmed or new hypothesis |
| 4. Implementation | Create test, fix, verify | Bug resolved, tests pass |

## Real-world impact

From debugging sessions:
- Systematic approach: 15-30 minutes to fix.
- Random-fixes approach: 2-3 hours of thrashing.
- First-time fix rate: 95% vs 40%.
- New bugs introduced: near zero vs common.
