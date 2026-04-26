# Skill format

A **skill** is a markdown file describing a reusable methodology -- a recipe
the AI agent follows when working in a particular mode (debugging, designing,
reviewing, planning). Skills are not roles; roles are expert YAML profiles.
A role *uses* one or more skills. Composition happens at expert-load time
(see `swarm_core.experts.registry.ExpertProfile.composed_system_prompt`).

## Layout

```
swarm_core/skills/
+-- SKILL_FORMAT.md           <- this spec
+-- registry.py               <- Skill, SkillRegistry
+-- <skill_name>.md           <- one file per skill
```

## File header (required)

Skills use YAML frontmatter delimited by `---`:

```markdown
---
name: Systematic Debugging
slug: systematic_debugging
when_to_use: when encountering any bug, test failure, or unexpected behavior
version: 1.0.0
universal: false                   # true = auto-attached to every expert
attribution: "Adapted from obra/superpowers-skills <URL>"
---

# Skill body in markdown
...
```

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Human-readable name (used in "I'm using the X skill" announcements) |
| `slug` | yes | Identifier used in `uses_skills:` lists (must match file stem) |
| `when_to_use` | yes | One-line trigger criteria (situational, not structural) |
| `version` | yes | Semver |
| `universal` | no (default false) | If true, auto-attached to every expert |
| `attribution` | no | Cite source if ported from another project |

## Body conventions

A skill body should answer four questions:

1. **What is this for?** -- one paragraph, the principle.
2. **When to use / when NOT to use.** -- triggers + anti-triggers.
3. **The process.** -- numbered phases or steps with explicit gates.
4. **Red flags / common rationalizations.** -- what to watch for in your own
   reasoning that means "stop and follow the process".

Optionally:
- Quick reference table.
- Real-world impact metrics that justify the cost.
- Cross-references to other skills.

Skills MUST NOT contain expert-specific content (no "you are a security
expert"). They are role-agnostic; the expert YAML provides the role.

## Composition

When an expert is loaded, its `composed_system_prompt` is built as:

```
<expert.system_prompt>

<skill_1.body>

<skill_2.body>

...

<universal skill bodies, e.g. solid_dry>
```

Skills declared in `uses_skills:` are inserted in declared order; universal
skills (`universal: true`) are appended at the end. Duplicate slugs are
de-duplicated.

## Adding a new skill

1. Create `swarm_core/skills/<slug>.md` with the frontmatter above.
2. Run `pytest packages/swarm-core/tests/test_skills.py` -- the registry
   loads + validates the new skill.
3. Reference from expert YAMLs by adding `uses_skills: [<slug>]`.
4. Document in `docs/architecture/skill-composition.md` if it introduces a
   new methodology category.

## What skills are NOT

- Skills are not capability flags. They don't "enable" features in code.
  They shape the AI's reasoning at prompt time only.
- Skills are not policies. Policy lives in code (e.g. `kb_check_quality_gate`).
- Skills are not single-tool concerns. A skill is portable across tools by
  construction (no tool-specific paths in the body).
