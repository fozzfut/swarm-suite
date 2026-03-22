"""DocSwarm -- Multi-agent documentation generator."""

__version__ = "0.1.3"

from .code_analyzer import CodeAnalyzer
from .doc_generator import DocGenerator
from .doc_verifier import DocVerifier
from .session import Session, SessionManager

__all__ = [
    "CodeAnalyzer",
    "DocGenerator",
    "DocVerifier",
    "Session",
    "SessionManager",
    "__version__",
]
