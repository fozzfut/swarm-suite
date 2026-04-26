# Swarm Suite — Installation Guide

Complete installation and upgrade guide for the swarm suite:
**ReviewSwarm**, **ArchSwarm**, **DocSwarm**, **FixSwarm**, **SpecSwarm**, and **SwarmKB**.

---

## Requirements

- **Python 3.10+**
- **uv** — fast Python package manager ([install uv](https://docs.astral.sh/uv/getting-started/installation/))

Install uv if you don't have it:

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Install the full suite

```bash
uv tool install review-swarm swarm-kb arch-swarm-ai doc-swarm-ai fix-swarm-ai spec-swarm-ai
```

Or install individual packages:

```bash
uv tool install review-swarm    # Code review
uv tool install swarm-kb        # Shared knowledge base
uv tool install arch-swarm-ai   # Architecture analysis
uv tool install doc-swarm-ai    # Documentation generation
uv tool install fix-swarm-ai    # Code fixing from reports
uv tool install spec-swarm-ai   # Hardware spec analysis
```

Verify:

```bash
review-swarm --version
swarm-kb --version
arch-swarm --version
doc-swarm --version
fix-swarm --version
spec-swarm --version
```

---

## Upgrade

Upgrade all at once:

```bash
uv tool upgrade review-swarm swarm-kb arch-swarm-ai doc-swarm-ai fix-swarm-ai spec-swarm-ai
```

Or individually:

```bash
uv tool upgrade review-swarm
```

> **Windows note:** If Claude Code is running, MCP servers hold locks on the exe files.
> Close Claude Code before upgrading, or see [Troubleshooting](#windows-exe-locks) below.

---

## MCP Setup (Claude Code)

After installing, register the MCP servers:

```bash
claude mcp add review-swarm -- review-swarm serve --transport stdio
claude mcp add swarm-kb     -- swarm-kb serve --transport stdio
claude mcp add arch-swarm   -- arch-swarm serve --transport stdio
claude mcp add doc-swarm    -- doc-swarm serve --transport stdio
claude mcp add fix-swarm    -- fix-swarm serve --transport stdio
```

Or add manually to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "review-swarm": {
      "command": "review-swarm",
      "args": ["serve", "--transport", "stdio"]
    },
    "swarm-kb": {
      "command": "swarm-kb",
      "args": ["serve", "--transport", "stdio"]
    },
    "arch-swarm": {
      "command": "arch-swarm",
      "args": ["serve", "--transport", "stdio"]
    },
    "doc-swarm": {
      "command": "doc-swarm",
      "args": ["serve", "--transport", "stdio"]
    },
    "fix-swarm": {
      "command": "fix-swarm",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

> Use bare command names (e.g. `"review-swarm"`), not absolute paths.
> This way the config survives upgrades and install method changes.

---

## MCP Setup (Cursor / Windsurf / Cline)

Start servers with SSE transport, then point the IDE at the URL:

```bash
review-swarm serve --port 8787
swarm-kb serve --port 8788
arch-swarm serve --port 8789
doc-swarm serve --port 8790
fix-swarm serve --port 8791
```

```json
{
  "mcpServers": {
    "review-swarm": { "url": "http://127.0.0.1:8787/sse" },
    "swarm-kb":     { "url": "http://127.0.0.1:8788/sse" },
    "arch-swarm":   { "url": "http://127.0.0.1:8789/sse" },
    "doc-swarm":    { "url": "http://127.0.0.1:8790/sse" },
    "fix-swarm":    { "url": "http://127.0.0.1:8791/sse" }
  }
}
```

---

## Troubleshooting

### Windows: exe locks

Claude Code spawns MCP servers as long-running processes. Windows locks open exe files,
so `uv tool upgrade` may fail while Claude Code is running.

**Solution:** Close Claude Code before upgrading. If that's not possible:

```bash
# Kill all swarm MCP server processes
taskkill /F /IM review-swarm.exe 2>/dev/null
taskkill /F /IM swarm-kb.exe 2>/dev/null
taskkill /F /IM arch-swarm.exe 2>/dev/null
taskkill /F /IM doc-swarm.exe 2>/dev/null
taskkill /F /IM fix-swarm.exe 2>/dev/null
taskkill /F /IM spec-swarm.exe 2>/dev/null

# Then upgrade
uv tool upgrade review-swarm swarm-kb arch-swarm-ai doc-swarm-ai fix-swarm-ai spec-swarm-ai
```

After upgrading, restart Claude Code — it will re-spawn the MCP servers automatically.

### PATH shadowing (after migrating from pip)

If you previously installed via pip and now use uv, stale exe shims in
`Python312/Scripts/` may shadow the uv-installed binaries in `~/.local/bin/`.

**Symptom:** `ModuleNotFoundError: No module named 'review_swarm'` after install.

**Fix:** Delete stale exe files from pip's Scripts directory:

```bash
# Find the stale exe (adjust Python version as needed)
ls ~/AppData/Local/Programs/Python/Python312/Scripts/review-swarm*
ls ~/AppData/Local/Programs/Python/Python312/Scripts/swarm-kb*
ls ~/AppData/Local/Programs/Python/Python312/Scripts/arch-swarm*
ls ~/AppData/Local/Programs/Python/Python312/Scripts/doc-swarm*
ls ~/AppData/Local/Programs/Python/Python312/Scripts/fix-swarm*
ls ~/AppData/Local/Programs/Python/Python312/Scripts/spec-swarm*

# Delete them
rm ~/AppData/Local/Programs/Python/Python312/Scripts/review-swarm*
rm ~/AppData/Local/Programs/Python/Python312/Scripts/swarm-kb*
# ... etc.
```

Or use the developer migration script: `scripts/migrate-to-uv.py` (see below).

### Verify installation

```bash
# Check which binary is being used
which review-swarm    # should point to ~/.local/bin/
review-swarm --version
```

---

## For Developers: Migrating from pip to uv

If you had the suite installed via pip and want to switch to uv cleanly,
use the migration script in the repo:

```bash
python scripts/migrate-to-uv.py
```

This script:
1. Kills running MCP server processes
2. Uninstalls packages from pip (both system and user site-packages)
3. Cleans stale exe shims from `Python312/Scripts/`
4. Removes leftover `~` directories from site-packages
5. Installs all packages via `uv tool install`
6. Verifies the installation

Run with `--dry-run` to preview actions without making changes.

---

## Uninstall

```bash
uv tool uninstall review-swarm swarm-kb arch-swarm-ai doc-swarm-ai fix-swarm-ai spec-swarm-ai
```

Session data in `~/.swarm-kb/` and `~/.review-swarm/` is preserved. Delete manually if needed.
