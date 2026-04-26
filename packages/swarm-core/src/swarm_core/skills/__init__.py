"""Reusable methodology recipes -- composed into expert prompts at load time.

A skill describes HOW to think in a particular mode (debug, design, review,
plan). An expert (YAML role profile) declares which skills it uses; the
composition happens in `swarm_core.experts.registry.ExpertProfile`.

See `SKILL_FORMAT.md` in this directory for the file format.
"""

from .registry import Skill, SkillRegistry, default_registry

__all__ = ["Skill", "SkillRegistry", "default_registry"]
