# swarm-core

Shared foundation for the [Swarm Suite](https://github.com/fozzfut/swarm-suite). Pure-Python, no other Swarm Suite packages depend on each other through anything except this package and `swarm-kb`.

## What's here

- `swarm_core.ids` -- single helper for prefixed short IDs (`f-a1b2`, `fp-a1b2c3`).
- `swarm_core.timeutil` -- `now_iso()` UTC ISO 8601 timestamps.
- `swarm_core.io` -- `atomic_write_text` (tempfile + os.replace).
- `swarm_core.models` -- canonical enums and base dataclasses (`Severity`, `ReactionType`, `Event`, `Message`, `Reaction`, `Claim`).
- `swarm_core.experts` -- `ExpertRegistry` + pluggable suggest strategies.
- `swarm_core.sessions` -- `SessionLifecycle` template-method base (mkdir, meta.json, prune, list).
- `swarm_core.coordination` -- `MessageBus`, `EventBus`, `PhaseBarrier`, `ClaimRegistry`, `RateLimiter`.
- `swarm_core.mcp` -- `MCPApp` builder (transport, tool registration, error wrapping, structured logging).
- `swarm_core.reports` -- `ReportRenderer` ABC + markdown helpers.
- `swarm_core.logging_setup` -- `setup_logging(tool_name)` and `get_logger(name)`.
- `swarm_core.keeper` -- `claude_md_keeper` audit (rules vs accreted bug-fix recipes).

## Install

```bash
pip install swarmsuite-core
```

This package is a runtime dep of every other Swarm Suite package; you usually install it transitively.

## Layering

```
swarm_core            <- here (zero in-suite deps)
   ^
   |
swarm_kb              <- storage layer
   ^
   |
spec/arch/review/fix/doc-swarm   <- tools
```

Layer violations are caught by `scripts/check_imports.py` in CI.
