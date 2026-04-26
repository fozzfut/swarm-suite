"""Unified code-map models -- superset of DocSwarm and ArchSwarm data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FunctionInfo:
    """Function or method extracted from source code."""

    name: str
    file: str
    line_start: int = 0
    line_end: int = 0
    signature: str = ""
    docstring: str = ""
    is_public: bool = True
    decorators: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "signature": self.signature,
            "docstring": self.docstring,
            "is_public": self.is_public,
            "decorators": self.decorators,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) ->FunctionInfo:
        return cls(
            name=d.get("name", ""),
            file=d.get("file", ""),
            line_start=d.get("line_start", 0),
            line_end=d.get("line_end", 0),
            signature=d.get("signature", ""),
            docstring=d.get("docstring", ""),
            is_public=d.get("is_public", True),
            decorators=d.get("decorators", []),
        )


@dataclass
class ClassInfo:
    """Class extracted from source code."""

    name: str
    file: str
    line_start: int = 0
    line_end: int = 0
    docstring: str = ""
    methods: list[FunctionInfo] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    is_public: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "docstring": self.docstring,
            "methods": [m.to_dict() for m in self.methods],
            "bases": self.bases,
            "is_public": self.is_public,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) ->ClassInfo:
        return cls(
            name=d.get("name", ""),
            file=d.get("file", ""),
            line_start=d.get("line_start", 0),
            line_end=d.get("line_end", 0),
            docstring=d.get("docstring", ""),
            methods=[FunctionInfo.from_dict(m) for m in d.get("methods", [])],
            bases=d.get("bases", []),
            is_public=d.get("is_public", True),
        )


@dataclass
class UnifiedModuleInfo:
    """Module info combining DocSwarm detail and ArchSwarm metrics."""

    file: str
    name: str = ""
    docstring: str = ""
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    lines_of_code: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "name": self.name,
            "docstring": self.docstring,
            "classes": [c.to_dict() for c in self.classes],
            "functions": [f.to_dict() for f in self.functions],
            "imports": self.imports,
            "lines_of_code": self.lines_of_code,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) ->UnifiedModuleInfo:
        return cls(
            file=d.get("file", ""),
            name=d.get("name", ""),
            docstring=d.get("docstring", ""),
            classes=[ClassInfo.from_dict(c) for c in d.get("classes", [])],
            functions=[FunctionInfo.from_dict(f) for f in d.get("functions", [])],
            imports=d.get("imports", []),
            lines_of_code=d.get("lines_of_code", 0),
        )


@dataclass
class CouplingMetrics:
    """Afferent/efferent coupling for a module (Robert C. Martin)."""

    module: str
    afferent: int = 0
    efferent: int = 0

    @property
    def instability(self) -> float:
        """Ce / (Ca + Ce). 0 = maximally stable, 1 = maximally unstable."""
        total = self.afferent + self.efferent
        return self.efferent / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "afferent": self.afferent,
            "efferent": self.efferent,
            "instability": round(self.instability, 3),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) ->CouplingMetrics:
        return cls(
            module=d.get("module", ""),
            afferent=d.get("afferent", 0),
            efferent=d.get("efferent", 0),
        )


@dataclass
class ProjectCodeMap:
    """Complete code-map for a project."""

    root: str
    scanned_at: str = ""
    modules: list[UnifiedModuleInfo] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)
    coupling: list[CouplingMetrics] = field(default_factory=list)
    class_hierarchy: dict[str, list[str]] = field(default_factory=dict)
    complexity_scores: dict[str, int] = field(default_factory=dict)

    @property
    def total_modules(self) -> int:
        return len(self.modules)

    @property
    def total_lines(self) -> int:
        return sum(m.lines_of_code for m in self.modules)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "scanned_at": self.scanned_at,
            "modules": [m.to_dict() for m in self.modules],
            "dependency_graph": self.dependency_graph,
            "coupling": [c.to_dict() for c in self.coupling],
            "class_hierarchy": self.class_hierarchy,
            "complexity_scores": self.complexity_scores,
        }
