---
title: Report Generator
type: api
status: draft
source_files:
- src/review_swarm/report_generator.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/report_generator.py
lines_of_code: 185
classes:
- ReportGenerator
functions: []
---

# Report Generator

Markdown and JSON report generation from findings.

**Source:** `src/review_swarm/report_generator.py` | **Lines:** 185

## Dependencies

- `__future__`
- `collections`
- `finding_store`
- `json`
- `models`

## Classes

### `class ReportGenerator`

**Lines:** 13-185

**Methods:**

- `def generate(self, session_id: str, fmt: str='markdown') -> str`
- `def generate_sarif(self, session_id: str) -> str` — Generate SARIF 2.1.0 output for GitHub Code Scanning integration.
