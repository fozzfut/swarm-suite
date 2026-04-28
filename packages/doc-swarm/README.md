# doc-swarm

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands — they never read this file. This README documents the package itself for contributors and standalone users.

Multi-agent **documentation generator + verifier**. Eight specialised experts (API reference, tutorial writer, README quality, architecture docs, inline docs, changelog, migration guide, error messages) scan your code, regenerate stale docs, verify existing docs against the actual codebase, and identify gaps.

This is **Stage 6** of the Swarm Suite pipeline (optional, run once near release): verify stale docs → regenerate API reference → update changelog.

## Install

```bash
pip install doc-swarm-ai
```

## Connect to your AI client

```bash
# Claude Code (built and tested)
claude mcp add doc-swarm -- doc-swarm serve --transport stdio
```

For Cursor / Windsurf / Cline (untested but should work via MCP), see the main [README § Connect to your AI client](../../README.md#connect-to-your-ai-client).

## CLI (standalone usage)

```bash
doc-swarm scan . --scope src/                    # show code map (Obsidian-compatible)
doc-swarm generate . --scope src/ --output docs  # generate Markdown docs
doc-swarm verify . --docs docs                   # verify existing docs vs code
```

## Expert profiles (8)

| Slug | Specialisation |
|------|----------------|
| `api-reference` | Verifies public APIs (functions, classes, endpoints) have complete, accurate docstrings. |
| `tutorial-writer` | Tutorial flow, prerequisites, working examples, progressive complexity. |
| `readme-quality` | README completeness: description, badges, installation, usage. |
| `architecture-docs` | Validates ADRs / design docs / system diagrams match the codebase. |
| `inline-docs` | Comment quality: misleading comments, outdated TODOs, stale references. |
| `changelog-expert` | Keep-a-Changelog + semver compliance; accurate change summaries. |
| `migration-guide` | Breaking changes coverage; before/after examples; upgrade paths. |
| `error-messages` | User-facing error messages: what went wrong, why, what to do next. |

Every expert auto-loads the universal **SOLID + DRY** and **karpathy-guidelines** skills.

## Cost

Documentation generation is one of the heavier stages — full doc regeneration on a medium project can run into many LLM calls. See the main [README § A note on cost](../../README.md#a-note-on-cost) before launching.

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
