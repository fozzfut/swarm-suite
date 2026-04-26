"""Attach `uses_skills:` declarations to expert YAMLs.

Per-tool defaults map each tool's experts to a list of skill slugs.
The script edits every YAML to set `uses_skills:` to the merged set
of (existing + tool-default + per-expert override). Idempotent.

Universal skills (solid_dry, karpathy_guidelines) are NOT added here --
they're attached automatically at compose time by ExpertProfile.

Run from repo root:
    python scripts/attach_skills.py [--dry-run]
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

# Per-tool defaults applied to EVERY expert in the tool.
TOOL_DEFAULTS: dict[str, list[str]] = {
    # fix-swarm: every expert proposes patches -> systematic_debugging is the
    # methodology gate; self_review is the publish gate.
    "fix-swarm": ["systematic_debugging", "self_review"],
    # review-swarm: every expert posts findings -> self_review is the publish gate.
    "review-swarm": ["self_review"],
    # arch-swarm: every expert reasons about design -> brainstorming for new
    # debates, self_review for proposals.
    "arch-swarm": ["self_review"],
    # spec-swarm: every expert extracts/verifies hardware facts -> self_review
    # before posting register/pin claims.
    "spec-swarm": ["self_review"],
    # doc-swarm: every expert produces text -> self_review before publishing.
    "doc-swarm": ["self_review"],
}

# Per-expert overrides (slug -> additional skill slugs).
PER_EXPERT_EXTRA: dict[str, list[str]] = {
    # The arch-swarm "tradeoff-mediator" expert is the role that runs
    # brainstorming-style debates -- give it the skill explicitly.
    "tradeoff-mediator": ["brainstorming"],
}


def tool_for(expert_dir: Path) -> str:
    return expert_dir.parents[2].name


def merged_skills(existing: list[str], tool_defaults: list[str], slug: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in existing + tool_defaults + PER_EXPERT_EXTRA.get(slug, []):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def process_yaml(path: Path, tool_defaults: list[str], *, dry_run: bool) -> str:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return "corrupt"
    if not isinstance(data, dict):
        return "corrupt"

    existing = data.get("uses_skills", []) or []
    if not isinstance(existing, list):
        existing = []

    slug = path.stem
    new_skills = merged_skills([str(s) for s in existing], tool_defaults, slug)

    if list(existing) == new_skills:
        return "already-set"

    data["uses_skills"] = new_skills
    if dry_run:
        return "updated"

    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )
    return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    totals: dict[str, int] = {"updated": 0, "already-set": 0, "corrupt": 0}
    for d in EXPERT_DIRS:
        if not d.is_dir():
            print(f"  [warn] {d} missing", file=sys.stderr)
            continue
        tool = tool_for(d)
        defaults = TOOL_DEFAULTS.get(tool, [])
        per = {"updated": 0, "already-set": 0, "corrupt": 0}
        for y in sorted(d.glob("*.yaml")):
            outcome = process_yaml(y, defaults, dry_run=args.dry_run)
            per[outcome] += 1
            totals[outcome] += 1
            if outcome == "corrupt":
                print(f"  [corrupt] {y.relative_to(REPO_ROOT)}", file=sys.stderr)
        print(f"{tool}: updated={per['updated']} already-set={per['already-set']} corrupt={per['corrupt']}")

    print()
    print(f"Total: updated={totals['updated']} already-set={totals['already-set']} corrupt={totals['corrupt']}")
    return 1 if totals["corrupt"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
