---
name: Test-Driven Development
slug: test_driven_development
when_to_use: when implementing new logic, fixing a bug (the prove-it pattern), or modifying behaviour that tests should verify
version: 1.0.0
universal: false
attribution: "Adapted from addyosmani/agent-skills (skills/test-driven-development/SKILL.md)"
---

# Test-Driven Development

## Overview

Write a failing test before writing the code that makes it pass. For bug fixes, reproduce the bug with a test before attempting a fix. Tests are proof — "seems right" is not done.

A codebase with good tests is an AI agent's superpower; a codebase without tests is a liability the agent has no way to verify itself against.

## When to Use

- Implementing any new logic or behaviour
- Fixing any bug (the **Prove-It Pattern** — see below)
- Modifying existing functionality
- Adding edge-case handling
- Any change that could break existing behaviour

**When NOT to use:** Pure configuration changes, documentation updates, or static-content changes with no behavioural impact.

## The TDD Cycle

```
   RED              GREEN             REFACTOR
Write a test ──→ Write minimal ──→ Clean up the
that fails       code to pass     implementation     ──→ (repeat)
     │                │                  │
     ▼                ▼                  ▼
 Test FAILS      Test PASSES        Tests still PASS
```

### RED — Write a Failing Test

It must fail. A test that passes immediately proves nothing.

```python
# RED: this fails because compute_crc16 doesn't exist yet
def test_crc16_known_vector():
    assert compute_crc16(b"\xAB\xCD") == 0x4B37
```

### GREEN — Make It Pass with the Minimum Code

Don't over-engineer; make the test green and stop.

### REFACTOR — Clean Up

With tests green, improve the code without changing behaviour: extract shared logic, improve names, remove duplication. Run tests after every refactor step.

## The Prove-It Pattern (Bug Fixes)

When a bug is reported, **do not start by trying to fix it**. Start by writing a test that reproduces it.

```
Bug report ─→ Write a failing test that reproduces the bug ─→ Fix ─→ Test passes ─→ Run full suite
```

Bug fixes without a reproduction test are not done. The reproduction test is the regression guard for the next person who tries the same change.

## The Test Pyramid

Most tests should be small and fast; progressively fewer tests at higher levels.

```
        ╱╲
       ╱  ╲       E2E / hardware-in-the-loop (~5%)
      ╱────╲      Full system, real targets, slow
     ╱      ╲     Integration (~15%)
    ╱        ╲    Module + adjacent boundary
   ╱──────────╲   Unit (~80%)
  ╱            ╲  Pure logic, isolated, milliseconds
 ╱──────────────╲
```

**The Beyonce Rule:** if you liked it, you should have put a test on it. If a refactor breaks code and there was no test for it, that's on the original author, not the refactorer.

| Size | Constraints | Speed | Example |
|---|---|---|---|
| **Small** | Single process, no I/O, no network | ms | Pure function tests, decoders, formula checks |
| **Medium** | Localhost only, may use temp DB / files | seconds | Driver-against-fake, API tests, component tests |
| **Large** | Real hardware / external services allowed | minutes | HIL tests, performance benchmarks, staging integration |

## Writing Good Tests

### Test State, Not Interactions

Assert on the *outcome*, not on which internal methods were called. Interaction-based tests break when you refactor even if behaviour is unchanged.

### DAMP > DRY in Tests

In production code, DRY is usually right. In tests, **DAMP (Descriptive And Meaningful Phrases)** is better — each test should read like a specification without requiring the reader to trace shared helpers.

### Prefer Real Implementations Over Mocks

```
Most preferred → Least preferred
1. Real implementation     (highest confidence, catches real bugs)
2. Fake                    (in-memory version of a dependency)
3. Stub                    (returns canned data, no behaviour)
4. Interaction mock        (verifies method calls — use sparingly)
```

Use mocks only when the real implementation is too slow, non-deterministic, or has side effects you can't control (external APIs, hardware bench equipment). Over-mocking creates tests that pass while production breaks.

### Arrange-Act-Assert

```python
def test_overdue_flag_set_when_deadline_past():
    # Arrange
    task = create_task(deadline=datetime(2025, 1, 1))
    # Act
    flagged = check_overdue(task, now=datetime(2025, 1, 2))
    # Assert
    assert flagged.is_overdue is True
```

### One Assertion Per Concept

Split tests so each verifies one named behaviour. If a test name contains "and", split it.

### Name Tests Descriptively

A test name should read like a spec line: `test_register_write_clears_status_bit_on_read` beats `test_register3`.

## Test Anti-Patterns

| Anti-pattern | Problem | Fix |
|---|---|---|
| Testing implementation details | Refactors break tests even when behaviour is unchanged | Test inputs and outputs, not internals |
| Flaky tests (timing / order) | Erodes trust in the suite | Deterministic assertions, isolate state |
| Testing framework code | Wastes time testing third-party behaviour | Test only YOUR code |
| Snapshot abuse | Large snapshots no one reviews; break on every change | Use sparingly, review every diff |
| No isolation | Tests pass alone but fail together | Each test sets up and tears down its own state |
| Mocking everything | Tests pass; production breaks | Mock at boundaries only |

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "I'll write tests after the code works" | You won't. And tests written after the fact test implementation, not behaviour. |
| "This is too simple to test" | Simple code becomes complicated. The test documents expected behaviour. |
| "Tests slow me down" | Tests slow you down now. They speed you up every later change. |
| "I tested it manually" | Manual testing doesn't persist. Tomorrow's change can break it silently. |
| "It's just a prototype" | Prototypes become production code. Tests from day one prevent test debt. |
| "I can't unit-test code that talks to hardware" | Yes you can — extract the logic from the I/O. The bytes-in, bytes-out logic is unit-testable; only the actual transfer needs HIL. |

## Red Flags

- Writing code without any corresponding test
- Tests that pass on the first run before the implementation exists (didn't actually test the new code)
- "All tests pass" reported but no tests were actually run
- Bug fixes without a reproduction test
- Tests that test framework behaviour instead of application behaviour
- Test names that don't describe expected behaviour
- Skipped or disabled tests left in to make the suite green

## Verification

After completing any implementation:

- [ ] Every new behaviour has a corresponding test
- [ ] The full test suite passes
- [ ] Bug fixes include a reproduction test that failed before the fix
- [ ] Test names describe the behaviour being verified
- [ ] No tests were skipped or disabled
- [ ] Coverage hasn't decreased (if tracked)
