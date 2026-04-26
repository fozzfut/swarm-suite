"""Append the canonical SOLID+DRY block to every expert YAML's system_prompt.

Single source of truth: packages/swarm-core/.../SOLID_DRY_BLOCK.md.
Idempotent: skips files whose system_prompt already contains the marker.

Run from the repo root:
    python scripts/inject_solid_dry.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BLOCK_PATH = REPO_ROOT / "packages/swarm-core/src/swarm_core/experts/SOLID_DRY_BLOCK.md"
EXPERT_DIRS = (
    REPO_ROOT / "packages/arch-swarm/src/arch_swarm/experts",
    REPO_ROOT / "packages/review-swarm/src/review_swarm/experts",
    REPO_ROOT / "packages/fix-swarm/src/fix_swarm/experts",
    REPO_ROOT / "packages/spec-swarm/src/spec_swarm/experts",
    REPO_ROOT / "packages/doc-swarm/src/doc_swarm/experts",
)
MARKER = "## SOLID+DRY enforcement (apply to user code)"

# Per-tool intro paragraph -- gives the expert a tool-specific framing for
# WHY the SOLID+DRY block applies to it.
TOOL_INTROS: dict[str, str] = {
    "arch-swarm": (
        "When you propose, critique, or vote on a design, every option is "
        "evaluated against the SOLID+DRY criteria below. Designs that "
        "violate SRP, OCP, or DIP without a written trade-off justification "
        "are downvoted. Designs that introduce duplication where a single "
        "source of truth is feasible are downvoted."
    ),
    "review-swarm": (
        "When you scan code and post findings, SOLID+DRY violations are "
        "first-class issues -- post them as `category: design` with severity "
        "scaled to blast radius (a god class with many callers is HIGH; a "
        "duplicated helper is LOW). Always cite the principle in `actual:` "
        "and the canonical home in `expected:`."
    ),
    "fix-swarm": (
        "When you propose a fix, the patch MUST move the codebase toward "
        "SOLID+DRY, never away. A fix that suppresses a finding by adding "
        "a god method, swallowing a duplicated branch into a fatter "
        "function, or hard-coding a special case will be rejected by the "
        "consensus pass. Prefer extract-method, extract-class, "
        "introduce-abstraction over inline-condition-and-move-on."
    ),
    "spec-swarm": (
        "When you extract hardware specifications and propose constraints, "
        "frame them so the consuming software can satisfy DIP -- drivers "
        "behind interfaces, not consumed directly. Group register / pin "
        "/ protocol entities so each one belongs to a clear module boundary "
        "(SRP) and is replaceable for hardware variants (OCP)."
    ),
    "doc-swarm": (
        "When you generate or verify documentation, the docs MUST capture "
        "the SOLID+DRY trade-offs that motivated each design choice. An ADR "
        "without a SOLID/DRY justification is incomplete; an API reference "
        "that hides a layering rule is misleading. Prefer one canonical doc "
        "per concept; cross-link rather than copy."
    ),
}


def load_block() -> str:
    if not BLOCK_PATH.is_file():
        raise FileNotFoundError(f"Canonical SOLID+DRY block missing: {BLOCK_PATH}")
    return BLOCK_PATH.read_text(encoding="utf-8").rstrip() + "\n"


def tool_for(expert_dir: Path) -> str:
    # packages/<tool>/src/<pkg>/experts -> <tool>
    return expert_dir.parents[2].name


def process_yaml(yaml_path: Path, block: str, intro: str, *, dry_run: bool) -> str:
    """Return one of: 'updated', 'skipped', 'corrupt'."""
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return "corrupt"
    if not isinstance(data, dict):
        return "corrupt"

    prompt = data.get("system_prompt", "")
    if not isinstance(prompt, str):
        return "corrupt"

    if MARKER in prompt:
        return "skipped"

    appended = prompt.rstrip()
    if appended:
        appended += "\n\n"
    appended += intro.strip() + "\n\n" + block

    data["system_prompt"] = appended
    if dry_run:
        return "updated"

    yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )
    return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing files.")
    args = parser.parse_args()

    block = load_block()
    totals: dict[str, int] = {"updated": 0, "skipped": 0, "corrupt": 0}

    for expert_dir in EXPERT_DIRS:
        if not expert_dir.is_dir():
            print(f"  [warn] {expert_dir} missing -- skipping", file=sys.stderr)
            continue
        tool = tool_for(expert_dir)
        intro = TOOL_INTROS.get(tool, "")
        per_dir = {"updated": 0, "skipped": 0, "corrupt": 0}
        for yaml_path in sorted(expert_dir.glob("*.yaml")):
            outcome = process_yaml(yaml_path, block, intro, dry_run=args.dry_run)
            per_dir[outcome] += 1
            totals[outcome] += 1
            if outcome == "corrupt":
                print(f"  [corrupt] {yaml_path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print(f"{tool}: updated={per_dir['updated']} skipped={per_dir['skipped']} corrupt={per_dir['corrupt']}")

    print()
    print(f"Total: updated={totals['updated']} skipped={totals['skipped']} corrupt={totals['corrupt']}")
    return 1 if totals["corrupt"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
