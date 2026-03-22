"""Data models for DocSwarm."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TypedDict

import yaml


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Enums ────────────────────────────────────────────────────────────


class DocStatus(str, Enum):
    """Status of a documentation file."""
    MISSING = "missing"          # code exists, no docs
    OUTDATED = "outdated"        # docs exist but don't match code
    ACCURATE = "accurate"        # docs match code
    DRAFT = "draft"              # generated, not verified
    VERIFIED = "verified"        # verified by multiple agents


class DocType(str, Enum):
    """Type of documentation."""
    API = "api"                  # API reference (functions, classes, params)
    GUIDE = "guide"              # How-to guide
    ARCHITECTURE = "architecture"  # System design
    REFERENCE = "reference"      # Config, CLI, glossary
    INDEX = "index"              # Navigation/RAG index


class Severity(str, Enum):
    """Severity of a documentation issue."""
    CRITICAL = "critical"    # docs actively mislead (wrong API, wrong behavior)
    HIGH = "high"            # missing docs for public API
    MEDIUM = "medium"        # outdated examples, stale references
    LOW = "low"              # style, formatting, minor inaccuracies
    INFO = "info"            # suggestion, not a problem


# ── Code Map ─────────────────────────────────────────────────────────


class FunctionInfo(TypedDict, total=False):
    name: str
    file: str
    line_start: int
    line_end: int
    signature: str
    docstring: str
    is_public: bool
    decorators: list[str]


class ClassInfo(TypedDict, total=False):
    name: str
    file: str
    line_start: int
    line_end: int
    docstring: str
    methods: list[FunctionInfo]
    bases: list[str]
    is_public: bool


class ModuleInfo(TypedDict, total=False):
    file: str
    docstring: str
    classes: list[ClassInfo]
    functions: list[FunctionInfo]
    imports: list[str]
    lines_of_code: int


# ── Documentation Issue ──────────────────────────────────────────────


@dataclass
class DocIssue:
    """A documentation issue found during verification."""

    id: str
    session_id: str
    expert_role: str
    file: str              # docs file path
    source_file: str       # code file path
    severity: Severity
    title: str
    description: str       # what's wrong
    suggestion: str        # how to fix
    confidence: float = 0.5
    status: DocStatus = DocStatus.OUTDATED
    created_at: str = ""

    @staticmethod
    def generate_id() -> str:
        return "di-" + secrets.token_hex(3)

    def __post_init__(self):
        if not self.id:
            self.id = DocIssue.generate_id()
        if not self.created_at:
            self.created_at = now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "expert_role": self.expert_role,
            "file": self.file,
            "source_file": self.source_file,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "status": self.status.value,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DocIssue:
        return cls(
            id=d.get("id", DocIssue.generate_id()),
            session_id=d.get("session_id", ""),
            expert_role=d.get("expert_role", ""),
            file=d.get("file", ""),
            source_file=d.get("source_file", ""),
            severity=Severity(d.get("severity", "medium")),
            title=d.get("title", ""),
            description=d.get("description", ""),
            suggestion=d.get("suggestion", ""),
            confidence=d.get("confidence", 0.5),
            status=DocStatus(d.get("status", "outdated")),
            created_at=d.get("created_at", ""),
        )


# ── Doc Page ─────────────────────────────────────────────────────────


@dataclass
class DocPage:
    """A generated or verified documentation page."""

    path: str              # relative path in docs/
    doc_type: DocType
    title: str
    source_files: list[str] = field(default_factory=list)  # code files this doc covers
    frontmatter: dict = field(default_factory=dict)
    content: str = ""
    status: DocStatus = DocStatus.DRAFT
    generated_by: str = ""  # expert_role that generated this
    verified_by: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = now_iso()
        if not self.updated_at:
            self.updated_at = now_iso()

    def to_markdown(self) -> str:
        """Render as markdown with YAML frontmatter."""
        lines = ["---"]
        fm = {
            "title": self.title,
            "type": self.doc_type.value,
            "status": self.status.value,
            "source_files": self.source_files,
            "generated_by": self.generated_by,
            "verified_by": self.verified_by,
            **self.frontmatter,
        }
        lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
        lines.append("---")
        lines.append("")
        lines.append(self.content)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "doc_type": self.doc_type.value,
            "title": self.title,
            "source_files": self.source_files,
            "frontmatter": self.frontmatter,
            "content": self.content,
            "status": self.status.value,
            "generated_by": self.generated_by,
            "verified_by": self.verified_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DocPage:
        return cls(
            path=d.get("path", ""),
            doc_type=DocType(d.get("doc_type", "api")),
            title=d.get("title", ""),
            source_files=d.get("source_files", []),
            frontmatter=d.get("frontmatter", {}),
            content=d.get("content", ""),
            status=DocStatus(d.get("status", "draft")),
            generated_by=d.get("generated_by", ""),
            verified_by=d.get("verified_by", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )
