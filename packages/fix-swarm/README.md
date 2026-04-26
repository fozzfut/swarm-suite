# FixSwarm

Multi-agent code fixer that reads [ReviewSwarm](https://github.com/fozzfut/review-swarm) reports and applies fixes automatically.

FixSwarm is the **fix** part of the review -> fix -> docs workflow. It takes a ReviewSwarm `report.json`, parses findings, generates a fix plan with specific text replacements, and applies those fixes to your source files.

## Installation

```bash
pip install -e .
```

## Usage

### 1. Generate a fix plan (dry-run)

```bash
fix-swarm plan report.json --threshold medium --dry-run
```

Shows what changes FixSwarm would make without modifying any files.

### 2. Apply fixes

```bash
fix-swarm apply report.json --threshold medium --backup
```

Applies all planned fixes. Use `--backup` to create `.bak` files before modifying.

### 3. Verify fixes

```bash
fix-swarm verify report.json
```

Checks whether the fixes for each finding have been applied correctly.

## Severity Threshold

The `--threshold` flag filters findings by minimum severity. The order is:
`critical > high > medium > low > info`. Default is `medium`.

## Report Formats

FixSwarm supports both JSON and Markdown report formats produced by ReviewSwarm.

## License

MIT
