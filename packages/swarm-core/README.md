# swarm-core

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users never install this package directly — it's a runtime dependency of every other Swarm Suite tool and is pulled in transitively. This README is for contributors and standalone users.

**Shared foundation** for the Swarm Suite. Pure-Python, zero in-suite dependencies. Every other Swarm Suite package depends on this one (and on `swarm-kb`); the `*-swarm` tools never depend on each other.

## What's here

- `swarm_core.ids` — single helper for prefixed short IDs (`f-a1b2`, `fp-a1b2c3`).
- `swarm_core.timeutil` — `now_iso()` UTC ISO 8601 timestamps.
- `swarm_core.io` — `atomic_write_text` (tempfile + `os.replace` with Windows-safe retry).
- `swarm_core.models` — canonical enums and base dataclasses (`Severity`, `ReactionType`, `Event`, `Message`, `Reaction`, `Claim`).
- `swarm_core.experts` — `ExpertRegistry` + pluggable `SuggestStrategy` ABC.
- `swarm_core.skills` — `SkillRegistry` + composition into expert prompts (universal vs opt-in).
- `swarm_core.sessions` — `SessionLifecycle` template-method base (mkdir, meta.json, prune, list).
- `swarm_core.coordination` — `MessageBus`, `EventBus`, `PhaseBarrier`, `ClaimRegistry`, `RateLimiter`, `CompletionTracker`.
- `swarm_core.mcp` — `MCPApp` builder (transport, tool registration, error wrapping, structured logging middleware).
- `swarm_core.reports` — `ReportRenderer` ABC + Markdown helpers.
- `swarm_core.logging_setup` — `setup_logging(tool_name)` + `get_logger(name)` (rotating per-tool log files in `~/.swarm-kb/logs/`).
- `swarm_core.keeper` — `claude_md_keeper` audit (rules vs accreted bug-fix recipes).
- `swarm_core.textmatch` — Jaccard similarity for task ↔ skill matching (used by `composed_system_prompt_for_task`).

## Install

```bash
pip install swarmsuite-core
```

> **Naming note:** the PyPI name is `swarmsuite-core` (the shorter `swarm-core` was rejected as too similar to existing `swarms`). The Python import name is still `swarm_core`.

## Layering

```
swarm_core            <- this package (zero in-suite deps)
   ^
   |
swarm_kb              <- storage + coordination
   ^
   |
spec / arch / review / fix / doc-swarm   <- tools (never depend on each other)
```

Layer violations are caught by `scripts/check_imports.py` in CI. Tools depend on `swarm_core` abstractions (ABCs in `swarm_core.experts`, `swarm_core.sessions`, `swarm_core.reports`), not concrete `swarm_kb` classes when an ABC exists.

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
