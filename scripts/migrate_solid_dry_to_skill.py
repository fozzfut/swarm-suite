"""Migrate the inline SOLID+DRY block out of expert YAMLs.

Before: every expert YAML's `system_prompt` ends with the SOLID+DRY block,
inserted by `inject_solid_dry.py`. The block lives twice -- once in
`packages/swarm-core/src/swarm_core/skills/solid_dry.md` (single source of
truth) and once duplicated into 53 YAMLs.

After this script: each YAML's `system_prompt` ends BEFORE the per-tool
intro paragraph + SOLID+DRY block. The universal `solid_dry` skill provides
the block at composition time. No change to what the AI sees.

Idempotent: running twice is a no-op.

Run from the repo root:
    python scripts/migrate_solid_dry_to_skill.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERT_DIRS = (
    REPO_ROOT / "packages/arch-swarm/src/arch_swarm/experts",
    REPO_ROOT / "packages/review-swarm/src/review_swarm/experts",
    REPO_ROOT / "packages/fix-swarm/src/fix_swarm/experts",
    REPO_ROOT / "packages/spec-swarm/src/spec_swarm/experts",
    REPO_ROOT / "packages/doc-swarm/src/doc_swarm/experts",
)

# These intros were prepended by inject_solid_dry.py before the marker.
# We strip from the start of the matched intro through end-of-prompt.
TOOL_INTROS: dict[str, list[str]] = {
    "arch-swarm": ["When you propose, critique, or vote on a design, every option is"],
    "review-swarm": ["When you scan code and post findings, SOLID+DRY violations are"],
    "fix-swarm": ["When you propose a fix, the patch MUST move the codebase toward"],
    "spec-swarm": ["When you extract hardware specifications and propose constraints,"],
    "doc-swarm": ["When you generate or verify documentation, the docs MUST capture"],
}

MARKER = "## SOLID+DRY enforcement (apply to user code)"


def tool_for(expert_dir: Path) -> str:
    return expert_dir.parents[2].name


def strip_inline_block(prompt: str, intros: list[str]) -> str | None:
    """Return prompt with the intro+block removed, or None if not present."""
    if MARKER not in prompt:
        return None  # already migrated or never injected

    # Find the intro line; strip from there. Falls back to stripping from
    # the marker if the intro can't be located.
    cut_at = -1
    for intro in intros:
        idx = prompt.find(intro)
        if idx >= 0 and (cut_at == -1 or idx < cut_at):
            cut_at = idx
    if cut_at < 0:
        cut_at = prompt.find(MARKER)

    return prompt[:cut_at].rstrip() + "\n"


def process_yaml(path: Path, intros: list[str], *, dry_run: bool) -> str:
    """Return one of: 'migrated', 'already-clean', 'corrupt'."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return "corrupt"
    if not isinstance(data, dict):
        return "corrupt"

    prompt = data.get("system_prompt", "")
    if not isinstance(prompt, str):
        return "corrupt"

    new_prompt = strip_inline_block(prompt, intros)
    if new_prompt is None:
        return "already-clean"

    data["system_prompt"] = new_prompt
    if dry_run:
        return "migrated"

    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )
    return "migrated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    totals: dict[str, int] = {"migrated": 0, "already-clean": 0, "corrupt": 0}
    for d in EXPERT_DIRS:
        if not d.is_dir():
            print(f"  [warn] {d} missing", file=sys.stderr)
            continue
        tool = tool_for(d)
        intros = TOOL_INTROS.get(tool, [])
        per = {"migrated": 0, "already-clean": 0, "corrupt": 0}
        for y in sorted(d.glob("*.yaml")):
            outcome = process_yaml(y, intros, dry_run=args.dry_run)
            per[outcome] += 1
            totals[outcome] += 1
            if outcome == "corrupt":
                print(f"  [corrupt] {y.relative_to(REPO_ROOT)}", file=sys.stderr)
        print(f"{tool}: migrated={per['migrated']} already-clean={per['already-clean']} corrupt={per['corrupt']}")

    print()
    print(f"Total: migrated={totals['migrated']} already-clean={totals['already-clean']} corrupt={totals['corrupt']}")
    return 1 if totals["corrupt"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
