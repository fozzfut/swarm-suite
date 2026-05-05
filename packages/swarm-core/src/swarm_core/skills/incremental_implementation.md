---
name: Incremental Implementation
slug: incremental_implementation
when_to_use: when implementing any feature or change that touches more than one file, or when you're about to write more than ~100 lines without testing
version: 1.0.0
universal: false
attribution: "Adapted from addyosmani/agent-skills (skills/incremental-implementation/SKILL.md)"
---

# Incremental Implementation

## Overview

Build in thin vertical slices — implement one piece, test it, verify it, commit it, then expand. Avoid implementing an entire feature in one pass. Each increment must leave the system in a working, testable state. This is the execution discipline that makes large changes safe.

## When to Use

- Multi-file changes
- New features (port a `next-step` from a Plan-stage breakdown)
- Refactors that touch more than one module
- Any time you're tempted to write more than ~100 lines before running tests

**When NOT to use:** Single-file, single-function changes whose scope is already minimal.

## The Increment Cycle

```
Implement ──→ Test ──→ Verify ──→ Commit ──→ Next slice
   ▲                                            │
   └────────────────────────────────────────────┘
```

For each slice:

1. **Implement** the smallest complete piece of functionality.
2. **Test** — run the affected tests, or write a test if none exists.
3. **Verify** — build / typecheck / lint pass; the slice does what it claims.
4. **Commit** — small, descriptive, atomic message.
5. **Move to the next slice** — carry forward, don't restart.

## Slicing Strategies

### Vertical Slices (Preferred)

Each slice is a complete path through the stack:

```
Slice 1: Read register X via SPI driver + simple test
Slice 2: Decode register fields + decoder test
Slice 3: Wire decoded value into the state machine + integration test
Slice 4: Surface in CLI / telemetry + end-to-end test
```

Every slice ends with the system *more capable* than before, not just *partially built*.

### Contract-First Slicing

When two layers must develop in parallel (e.g. firmware ↔ host driver):

```
Slice 0: Define the protocol contract (message format, opcodes, timing) — written and reviewed
Slice 1a: Firmware implements its half against the contract
Slice 1b: Host driver implements its half against a mock matching the contract
Slice 2: Integrate, verify with hardware-in-the-loop tests
```

### Risk-First Slicing

Tackle the most uncertain piece first — a failed slice 1 saves you from building slices 2–4 on a broken foundation:

```
Slice 1: Prove the I2C bus reaches 1 MHz reliably (highest risk)
Slice 2: Implement transactions on that proven bus
Slice 3: Add error recovery and retry policy
```

## Implementation Rules

### Rule 0 — Simplicity First

Before writing code: *what is the simplest thing that could work?* After writing: *can this be done in fewer lines? Are these abstractions earning their complexity?* Three similar lines of code beats a premature abstraction. Implement the obviously-correct version first; optimise only after correctness is proven.

### Rule 0.5 — Scope Discipline

Touch only what the task requires. Do **NOT**:
- "Clean up" code adjacent to your change
- Refactor imports in files you're not modifying
- Remove comments you don't fully understand
- Add features not in the spec because they "seem useful"
- Modernise syntax in files you're only reading

If you notice something worth improving outside scope, *note it, don't fix it*. Open a separate finding or decision.

### Rule 1 — One Thing at a Time

Each increment changes one logical thing. **Bad:** one commit that adds a new driver, refactors an existing one, and updates the build config. **Good:** three separate commits.

### Rule 2 — Keep It Compilable

After each increment, the project must build and existing tests must pass. Don't leave the codebase in a broken state between slices.

### Rule 3 — Feature Flags for In-Progress Work

If you must merge increments before the feature is user-ready, gate it:

```c
#ifdef ENABLE_NEW_TEMPERATURE_COMP
    apply_compensation(&adc_raw, calib);
#endif
```

This lets small increments land on `main` without exposing incomplete behaviour.

### Rule 4 — Safe Defaults

New code defaults to the conservative behaviour. Opt-in to the new path; don't break the old one without explicit migration.

### Rule 5 — Rollback-Friendly

Each increment must be independently revertable. Additive changes (new files / functions) are easy to revert; modifications should be minimal and focused. For schema changes, ship the rollback alongside.

## Increment Checklist

After each slice, confirm:

- [ ] The change does one thing and does it completely
- [ ] All existing tests pass
- [ ] The build / type-check / lint succeed
- [ ] The new functionality works as expected (manual or automated)
- [ ] The change is committed with a descriptive message

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "I'll test it all at the end" | Bugs compound. A bug in slice 1 makes slices 2–N wrong. Test each slice. |
| "It's faster to do it all at once" | It *feels* faster until something breaks and you can't bisect across 500 changed lines. |
| "These changes are too small to commit separately" | Small commits are free. Large commits hide bugs and make rollbacks painful. |
| "I'll add the feature flag later" | If the feature isn't complete, it shouldn't be user-visible. Add the flag now. |
| "This refactor is small enough to bundle in" | Refactor + feature in one commit makes both harder to review and to revert. Separate them. |

## Red Flags

- More than 100 lines of code written without running tests
- Multiple unrelated changes in a single commit
- "Let me just quickly add this too" scope expansion
- Skipping the test/verify step to move faster
- Build or tests broken between increments
- Large uncommitted changes piling up
- Building abstractions before the third use case demands it
- Touching files outside the task scope "while I'm here"

## Verification

After completing all increments for a task:

- [ ] Each increment was individually tested and committed
- [ ] The full test suite passes
- [ ] The build is clean
- [ ] The feature works end-to-end as specified
- [ ] No uncommitted changes remain
