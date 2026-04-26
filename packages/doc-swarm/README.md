# DocSwarm

Multi-agent documentation generator via MCP.

Scans your code, generates Obsidian-compatible markdown docs with frontmatter, verifies existing docs against code, and identifies gaps.

## Install

```bash
pip install doc-swarm
```

## Usage

```bash
# Scan project and show code map
doc-swarm scan . --scope src/

# Generate documentation
doc-swarm generate . --scope src/ --output docs

# Verify existing docs
doc-swarm verify . --docs docs
```

## License

MIT
