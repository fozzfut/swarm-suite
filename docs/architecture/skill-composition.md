# Skill composition

Expert YAMLs declare a role (security expert, refactoring expert, ...);
**skills** declare a methodology (systematic debugging, brainstorming,
self-review, ...). The two compose at expert-load time:

```
final prompt seen by AI =
    expert.system_prompt
    + each declared skill in `uses_skills:` (in order)
    + each universal skill (in load order, deduped)
```

Code: `swarm_core.experts.registry.ExpertProfile.composed_system_prompt`.

## Why composition (not inlining)

Inlining the SOLID+DRY block into 53 YAMLs (the previous design) had three
problems:

1. **Update friction.** Editing the block meant running an injection
   script across every YAML; old copies could drift.
2. **No reuse for new methodologies.** Adding `systematic_debugging` would
   have meant duplicating the block 8 more times (once per fix-swarm
   expert).
3. **YAML bloat.** A 100-line role with a 90-line methodology block makes
   the role hard to read at a glance.

Composition fixes all three: skill bodies live once; experts opt in; the
runtime assembles.

## Universal vs declared skills

| Skill | Universal? | Why |
|-------|-----------|-----|
| `solid_dry` | yes | Mission of the suite -- every expert enforces it |
| `karpathy_guidelines` | yes | Behavioral discipline applies to every AI agent |
| `self_review` | no (opt-in) | Heavy checklist; lite-mode tools should skip it |
| `systematic_debugging` | no (opt-in) | Only fix-swarm experts; review-swarm doesn't propose patches |
| `brainstorming` | no (opt-in) | Only arch-swarm `tradeoff-mediator` and the Idea-stage orchestrator |
| `writing_plans` | no (opt-in) | Only the Plan-stage orchestrator |

`universal: true` in the skill's frontmatter -> auto-attached to every
expert. `universal: false` -> attached only when the expert YAML lists
the slug in `uses_skills:`.

## Order matters

Sections appear in the composed prompt in this order:

1. **Role** (`expert.system_prompt`) -- "you are a Security Surface Expert,
   here are the patterns you check"
2. **Declared skills** (in YAML list order) -- e.g. `systematic_debugging`,
   then `self_review`
3. **Universal skills** (in skill registry load order, deduped) --
   `karpathy_guidelines`, `solid_dry`

This order matches how a human would read it: first "what role am I",
then "what specific methodology applies right now", then "what universal
behavior + output discipline always applies".

A skill listed in BOTH `uses_skills:` and as universal is shown once
(deduped by slug, declared position wins).

## Legacy SOLID+DRY suppression

Some YAMLs still inline the SOLID+DRY block (legacy migration period).
The composition logic detects the inline marker
(`## SOLID+DRY enforcement (apply to user code)`) via
`ExpertProfile.has_solid_dry_block()` and suppresses the universal
`solid_dry` skill body for that profile. Result: legacy and migrated
YAMLs both produce a sane prompt with exactly one copy of the block.

When `migrate_solid_dry_to_skill.py` has run on a YAML, the inline block
is removed and the universal skill takes over.

## Adding a new skill

1. Create `packages/swarm-core/src/swarm_core/skills/<slug>.md` with
   the format documented in `SKILL_FORMAT.md`.
2. Run `pytest packages/swarm-core/tests/test_skills.py` -- the registry
   loads + validates.
3. Either:
   - Mark it `universal: true` and it applies to every expert, OR
   - Run `scripts/attach_skills.py` after editing `TOOL_DEFAULTS` to
     opt-in specific tools' experts.
4. Document in `docs/architecture/skill-composition.md` if it introduces
   a new methodology category.

## Skills as layered discipline

The five skills shipped form three layers:

- **Behavioral** -- how the AI should reason while working.
  - `karpathy_guidelines` (universal)
- **Methodological** -- how to approach a particular kind of work.
  - `systematic_debugging` (fix-swarm experts)
  - `brainstorming` (Idea stage, arch debates)
  - `writing_plans` (Plan stage)
- **Output discipline** -- what every published artifact must satisfy.
  - `self_review` (every publishing expert)
  - `solid_dry` (universal, every output enforces it on user code)

By design these layers don't overlap. A new skill should pick a layer
and stay there.
