# 2026-04-26 -- Skill composition design

## Status

Implemented. `swarm-core` 0.1.0 ships with `swarm_core.skills/` and
`ExpertProfile.composed_system_prompt`. All 53 expert YAMLs carry
`uses_skills:` declarations (set by `scripts/attach_skills.py`). The
universal `solid_dry` and `karpathy_guidelines` skills auto-attach.

## Context

The user's review of the codebase versus the obra/superpowers-skills
plugin produced a clear architectural recommendation: skills should be
composable methodology recipes, not inline blocks pasted into 53 YAMLs.

Before this change:
- `inject_solid_dry.py` injected the SOLID+DRY block into every expert.
- Each YAML was 200-500 lines, duplicating ~90 lines of block content.
- Adding a new universal methodology (e.g. `karpathy_guidelines`) would
  require editing all 53 YAMLs again.
- Updating the SOLID+DRY block meant running the injection script and
  hoping no manual edits drifted.

## Decision

Skills live in `swarm_core/skills/<slug>.md` (markdown with YAML
frontmatter, identical format to obra/superpowers-skills). An
`ExpertRegistry` composes the final prompt at load time:

```
final = expert.system_prompt
        + each declared skill (in `uses_skills:` order)
        + each universal skill (deduped, in registry load order)
```

Universal skills (`universal: true`) auto-attach to every expert.
Declared skills opt in via `uses_skills:` in the YAML.

## Why composition wins over inlining

| Concern | Inlining | Composition |
|---------|----------|-------------|
| Update propagation | Run inject script, hope no drift | Edit one file, all consumers see change |
| New universal methodology | 53 YAML diffs | 1 markdown file |
| YAML readability | Bloated (block at end of each) | Lean (just role + `uses_skills:`) |
| Per-expert opt-in | Hand-edit YAMLs | List in `uses_skills:` |
| Layered discipline | Hard to see which methodology applies | Self-documenting via `uses_skills:` |

## Decision: SOLID+DRY moves from inline to universal skill

Migration:
- `swarm_core/skills/solid_dry.md` is the canonical body (already true).
- `scripts/migrate_solid_dry_to_skill.py` strips the inline block from
  53 YAMLs (run once, idempotent).
- `ExpertProfile.has_solid_dry_block()` retained as legacy detector for
  the migration window; `composed_system_prompt` suppresses the universal
  copy if the legacy marker is present (so half-migrated repos don't
  produce a duplicated block).

## Decision: per-tool skill defaults

`scripts/attach_skills.py` sets `uses_skills:` on every YAML according
to a per-tool default map:

| Tool | Default skills |
|------|----------------|
| `fix-swarm` | `[systematic_debugging, self_review]` |
| `review-swarm` | `[self_review]` |
| `arch-swarm` | `[self_review]` |
| `spec-swarm` | `[self_review]` |
| `doc-swarm` | `[self_review]` |

Per-expert overrides via `PER_EXPERT_EXTRA` (e.g.
`tradeoff-mediator` adds `brainstorming`).

This is a starting point -- experts can add or override via direct YAML
edit; the script is idempotent.

## Trade-offs accepted

- **Composition is runtime cost.** Every expert load reads N skill files.
  Mitigated by `SkillRegistry._cache` -- one parse per process.
- **Universal-skill bloat.** Adding `karpathy_guidelines` as universal
  means ~3KB extra per prompt across 53 experts. Worth it for the
  behavioral discipline; if cost ever matters, mark it `universal: false`
  and opt in selectively.
- **Two prompts to inspect** (`system_prompt` raw vs `composed_system_prompt`).
  `kb_check_claude_md` and similar audit tools should use the composed
  view to see what the AI actually receives.

## Acceptance

- `pytest packages/swarm-core/tests` -> 52 passed (8 new skill tests +
  4 new composition tests).
- `python scripts/check_imports.py` -> clean.
- End-to-end smoke test (`security-fix` expert) confirms exactly one
  copy of each skill body in the composed prompt; no duplicates;
  ordering is role -> declared -> universal.
