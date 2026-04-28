# spec-swarm

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands — they never read this file. This README documents the package itself for contributors and standalone users.

> **Optional, embedded only.** Skip this package entirely if you're not writing firmware or instrument software. The other six Swarm Suite packages run without it.

Hardware **specification analyzer** for embedded software development. Parses datasheets, reference manuals, and hardware documentation to extract structured data — register maps, pin configurations, protocol parameters (CAN/CANopen/EtherCAT/PROFINET/Modbus/OPC UA/…), timing constraints, power specifications, memory layouts. Makes this information available to AI agents via MCP tools **before any code exists**.

This is **Stage 0b** of the Swarm Suite pipeline: datasheets → registers, pins, protocols → conflict report (pin collisions, bus overload, power budget) → architectural constraints exported to arch-swarm.

## Install

```bash
pip install spec-swarm-ai

# For PDF datasheet ingestion
pip install spec-swarm-ai[pdf]
```

## Connect to your AI client

```bash
# Claude Code (built and tested)
claude mcp add spec-swarm -- spec-swarm serve --transport stdio
```

For Cursor / Windsurf / Cline (untested but should work via MCP), see the main [README § Connect to your AI client](../../README.md#connect-to-your-ai-client).

## CLI (standalone usage)

```bash
spec-swarm serve --transport stdio
spec-swarm ingest path/to/STM32F407_datasheet.pdf --component STM32F407VG
spec-swarm status
```

## Supported document formats

- **PDF** (requires `pymupdf` — install with `pip install spec-swarm-ai[pdf]`)
- Plain text (`.txt`), Markdown (`.md`), reStructuredText (`.rst`), CSV (`.csv`)

## MCP tools

| Tool | Description |
|------|-------------|
| `spec_start_session` | Start a spec analysis session for a project |
| `spec_list_sessions` | List all spec analysis sessions |
| `spec_ingest` | Ingest a document and extract hardware specs |
| `spec_add_manual` | Manually add a hardware specification |
| `spec_get_registers` | Get register map for a component |
| `spec_get_pins` | Get pin configuration |
| `spec_get_protocols` | Get communication protocol configurations |
| `spec_get_timing` | Get timing constraints |
| `spec_get_memory_map` | Get memory map regions |
| `spec_get_constraints` | Get all hardware constraints |
| `spec_search` | Search specs by keyword |
| `spec_check_conflicts` | Pin collisions, bus conflicts, power budget violations |
| `spec_suggest_experts` | Suggest spec expert profiles for the project |
| `spec_export_for_arch` | Export specs as architectural constraints for arch-swarm |
| `spec_get_summary` | Summary of all specs in a session |

## Expert profiles (14)

| Slug | Specialisation |
|------|----------------|
| `mcu-peripherals` | GPIO config, clock tree, interrupts, DMA channels. |
| `communication-protocols` | SPI, I2C, UART, CAN, USB, Ethernet — correctness, timing, signal integrity. |
| `industrial-protocols` | CAN, CANopen, EtherCAT, PROFINET, Modbus, OPC UA, EtherNet/IP, PROFIBUS, IO-Link, PROFIsafe, FSoE. |
| `power-management` | Power budget, voltage rail compatibility, sleep modes, current draw. |
| `sensor-interfaces` | ADC resolution, sampling rates, calibration, sensor fusion. |
| `motor-control` | PWM configurations, H-bridge drivers, encoders, commutation. |
| `memory-layout` | Flash/RAM partitioning, linker scripts, bootloader, OTA slots. |
| `timing-constraints` | Timing budgets, watchdog windows, real-time deadlines, jitter. |
| `safety-requirements` | IEC 61508, ISO 26262, redundancy, fail-safe states. |
| `requirements-analysis` | SRS / PRD / user stories / acceptance criteria; ambiguity flagging. |
| `api-specification` | OpenAPI / gRPC protobuf / GraphQL schemas; REST API completeness. |
| `system-integration` | Component connections, data flow, protocol bridges, error propagation. |
| `standards-compliance` | ISO 9001, IEC 61508, ISO 26262, DO-178C, MISRA, etc. |
| `configuration-spec` | Configuration files, environment variables, feature flags. |

Every expert auto-loads the universal **SOLID + DRY** and **karpathy-guidelines** skills.

## Integration with the rest of Swarm Suite

Extracted specifications are stored in swarm-kb and become available to:

- **arch-swarm** — hardware constraints inform architecture decisions and ADRs.
- **review-swarm** — verify code against datasheet requirements (register access, pin direction, timing).
- **fix-swarm** — apply hardware-aware fixes (correct register address, valid pin alternate function).

## Cost

Datasheet ingestion + multi-agent verification (Stage 0b) can be heavy on tokens, especially with `orchestrate_verification`. See the main [README § A note on cost](../../README.md#a-note-on-cost).

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
