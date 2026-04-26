# Expert profile format

Every expert lives as a single YAML file under
`packages/<tool>/src/<pkg>/experts/<slug>.yaml`. The `slug` (file stem)
is the canonical identifier used in MCP tool calls.

## Required fields

```yaml
name: "Security Surface Expert"        # human-readable
description: "Detects injection..."    # one-sentence summary
system_prompt: |                       # the prompt shown to the AI agent
  ...                                  # MUST end with the SOLID+DRY block
```

## Optional fields

```yaml
version: "1.0"
file_patterns: ["**/*.py", "**/*.ts"]   # globs the expert applies to
exclude_patterns: ["tests/**"]
relevance_signals:                      # used by ProjectScanStrategy
  imports: ["flask", "django"]
  patterns: ["request\\.", "cursor\\.execute"]
check_rules:                            # checks the expert performs
  - id: "injection-vector"
    description: "..."
    severity_default: "critical"
    check: |
      ...
severity_guidance:                      # how the expert should grade
  critical: "..."
  high: "..."
```

## The SOLID+DRY block (mandatory)

Every `system_prompt` ends with the canonical block defined in
`packages/swarm-core/src/swarm_core/experts/SOLID_DRY_BLOCK.md`. The
block opens with the marker:

```
## SOLID+DRY enforcement (apply to user code)
```

The marker is what `swarm_core.experts.ExpertProfile.has_solid_dry_block()`
matches. The injection script at `scripts/inject_solid_dry.py` is
idempotent: running it twice does not duplicate the block. It MUST be
re-run any time the canonical block is edited.

## Why every expert ends with the block

The Swarm Suite's mission is to take a Python project from idea to
production-grade SOLID+DRY code. That mission is implemented in the
prompts. An expert that does not enforce SOLID+DRY when reviewing,
fixing, designing, or documenting user code is not part of the
mission -- and the keeper script will refuse to ship a release where
any expert is missing the block.

## Adding a new expert

1. Pick the slug (lowercase, dash-separated, file stem).
2. Write the YAML in the right tool's `experts/` dir.
3. Compose the `system_prompt` ending with the marker line above
   (the injection script will append the canonical block on next run,
   but you can hand-write the block if you need to ship it before the
   next injection-script run).
4. Run `python scripts/inject_solid_dry.py` to keep all experts in sync.
5. Add a row to the relevant table in `GUIDE.md` and to
   `docs/INDEX.md` if the expert introduces a new keyword.

## Keeper-enforced invariants

- `name` is non-empty.
- `description` is non-empty.
- `system_prompt` is non-empty AND contains the SOLID+DRY block marker.
- `check_rules[].severity_default` is one of: `critical | high | medium | low | info`.
- File stem matches the slug used in any `category_to_expert` mapping
  in `swarm_core.experts.suggest`.
