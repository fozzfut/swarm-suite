"""monitor-swarm — trace analyzer for instrument software.

Parses runtime logs (text logs, Saleae Logic2 CSV) and cross-references
extracted timing measurements against spec-swarm hardware constraints,
emitting findings in the standard swarm-kb format.

Stage 9 in the suite — runs after Release on deployed instruments,
or during HIL testing as part of Hardening (Stage 7) when traces are
available before release.
"""

__version__ = "0.1.0a1"
