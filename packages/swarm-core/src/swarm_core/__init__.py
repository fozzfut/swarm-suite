"""Swarm Suite shared foundation.

Re-exports the most-used helpers; deeper APIs live in submodules.
"""

from .ids import generate_id
from .timeutil import now_iso

__version__ = "0.1.0"

__all__ = ["generate_id", "now_iso", "__version__"]
