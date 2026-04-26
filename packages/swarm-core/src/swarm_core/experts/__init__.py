"""Expert profile registry + pluggable suggest strategies.

`ExpertRegistry` discovers YAML profiles (built-in + custom dirs) and
delegates "given context X, which experts apply?" to a `SuggestStrategy`.
This is OCP in action: new strategies subclass; the registry is closed.
"""

from .registry import ExpertRegistry, ExpertProfile
from .suggest import (
    SuggestStrategy,
    ProjectScanStrategy,
    FindingMatchStrategy,
    NullSuggestStrategy,
)

__all__ = [
    "ExpertRegistry",
    "ExpertProfile",
    "SuggestStrategy",
    "ProjectScanStrategy",
    "FindingMatchStrategy",
    "NullSuggestStrategy",
]
