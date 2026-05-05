# monitor-swarm

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands. This README documents the package itself for contributors and standalone users.

> **Stage 9 of the pipeline (post-release operate / pre-release HIL).** Closes the loop on the niche: spec-swarm extracts datasheet facts; review-swarm/fix-swarm check code against them; monitor-swarm checks the *running device's behaviour* against them.

Trace analyzer for instrument software. Parses runtime logs (text logs, Saleae Logic2 CSV) and cross-references extracted timing measurements against spec-swarm timing constraints, emitting findings in the standard swarm-kb format. Findings flow into the same KB the rest of the suite uses, so review-swarm and fix-swarm can react to them without any new integration code.

## Install

```bash
pip install monitor-swarm-ai
```

## Connect to your AI client

```bash
# Claude Code
claude mcp add monitor-swarm -- monitor-swarm serve --transport stdio
```

## CLI

```bash
monitor-swarm serve --transport stdio       # MCP server over stdio
monitor-swarm serve --port 8770             # MCP server over SSE
monitor-swarm analyze trace.log --spec-constraints '[{"parameter":"t_conv","max_value":"120","unit":"us","source":"DS T47"}]'
monitor-swarm status                        # list monitor sessions
```

## MCP tools

| Tool | Description |
|------|-------------|
| `monitor_analyze_trace` | Parse a trace, extract timing measurements, cross-reference vs spec, emit findings into the KB. |
| `monitor_list_sessions` | List monitor sessions in the KB. |
| `monitor_get_session` | Get findings + meta for one session. |

## Supported trace formats

| Format | Parser | Notes |
|---|---|---|
| Plain text log | `text_log` | regex-driven; default pattern matches `[1.234] [INFO] channel: message` and ISO-8601 timestamps. Override via `log_pattern` if your firmware emits something else. |
| Saleae Logic2 CSV | `saleae_csv` | Both digital signal exports (one event per edge) and protocol-decoded exports (one event per row). |

`parser="auto"` (default) picks by file extension (`.csv`/`.tsv` → Saleae; everything else → text log).

## Detection: timing violations (v0)

Looking inside event payloads for inline timing parameters of the shape `<param>=<value><unit>` or `<param> took <value><unit>` — for example:

```
[12.345] [INFO] adc: t_conv = 137 us         ← extracted as t_conv=137us
[12.350] [INFO] spi: transaction took 4 ms   ← extracted as transaction=4ms
```

The detector then matches each parameter against the timing constraints you pass in (returned by `spec-swarm`'s `spec_get_timing`):

| measured vs spec | result |
|---|---|
| within `[min_value, max_value]` | no finding |
| above `max_value` | finding (severity `high`, or `critical` if the spec marks the constraint critical) |
| below `min_value` | finding (severity `high`, or `critical` if marked) |

Parameter names are matched leniently — `t_conv` in the spec matches `conv`, `t_conv`, or `timing_conv` in the log.

## Layering

monitor-swarm depends only on `swarm-core` + `swarm-kb` — never on `spec-swarm` directly. Spec data is passed in by the caller (the AI agent runs `spec_get_timing` first and forwards the result), keeping the existing layering rules intact. See `docs/architecture/layering.md`.

## Expert profile (1)

| Slug | Specialisation |
|------|----------------|
| `timing-analyst` | Interprets timing-violation findings, ranks by severity, generates root-cause hypotheses (ISR priorities, DMA config, clock-tree, blocking calls), recommends next diagnostic step. Does NOT propose fixes — that's fix-swarm's job. |

## Cost

The analyzer itself is deterministic (no LLM calls in the parser/detector). LLM cost only enters when the AI agent reads the resulting findings and reasons about them via the `timing-analyst` expert prompt. Expect costs on the order of a single fix-swarm `propose_fix` call per finding examined.

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
