---
name: Writing Plans
slug: writing_plans
when_to_use: when a design / ADR is approved and you need detailed bite-sized implementation tasks
version: 1.0.0
universal: false
attribution: "Adapted from obra/superpowers-skills (skills/collaboration/writing-plans/SKILL.md, v2.1.0)"
---

# Writing Plans

## Overview

Write a comprehensive implementation plan assuming the engineer (or autonomous agent) has zero context for this codebase. Document everything they need: which files to touch for each task, the code, the testing, the docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume the executor is a skilled developer who knows almost nothing about this toolset or problem domain, and is shaky on good test design.

**Save plans to:** `~/.swarm-kb/sessions/plan/<sid>/<feature-name>.md`.

## Bite-sized task granularity

Each step is one action (2-5 minutes):
- "Write the failing test" -- step
- "Run it to make sure it fails" -- step
- "Implement the minimal code to make the test pass" -- step
- "Run the tests and make sure they pass" -- step
- "Commit" -- step

A task that takes more than 5 minutes is too coarse; split it.

## Plan document header (required)

Every plan MUST start with this header:

```markdown
# <Feature Name> Implementation Plan

> **For the executing agent:** apply the `writing_plans` and `systematic_debugging` skills as you work. Use kb_quick_review after each task to catch regressions; rewind via kb_rewind_pipeline if Phase N invalidates an earlier ADR.

**Goal:** <One sentence describing what this builds>

**Architecture:** <2-3 sentences about approach; reference the ADR ID this plan implements>

**Tech stack:** <Key technologies/libraries>

**ADR refs:** <list of swarm-kb decision IDs this plan implements>

---
```

## Task structure

```markdown
### Task N: <Component Name>

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Step 1: Write the failing test**

\`\`\`python
def test_specific_behavior():
    result = function(input)
    assert result == expected
\`\`\`

**Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

**Step 3: Write minimal implementation**

\`\`\`python
def function(input):
    return expected
\`\`\`

**Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

**Step 5: Commit**

\`\`\`bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
\`\`\`
```

## Anti-patterns in plans

- Tasks like "implement the auth module" -- too coarse; split into 5-10 sub-tasks.
- Code shown as "add validation here" instead of the actual code -- the executor will skip it.
- Commands without expected output -- the executor can't verify success.
- No failing test before implementation -- you don't know the feature works; you know it didn't crash.
- "Refactor while you're at it" tasks bundled with feature work -- impossible to bisect when something breaks.

## Remember

- Exact file paths always.
- Complete code in the plan (not "add validation").
- Exact commands with expected output.
- DRY, YAGNI, TDD, frequent commits.
- One ADR -> one plan; one plan -> one feature.
