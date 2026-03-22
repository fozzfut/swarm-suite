"""Code analyzer -- scans source files and builds structured code map via AST."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from .models import ClassInfo, FunctionInfo, ModuleInfo

_log = logging.getLogger("doc_swarm.code_analyzer")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

_SKIP_DIRS = {
    "node_modules", ".venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".tox",
    ".eggs", "site-packages",
}

_SOURCE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".kt",
    ".cs", ".cpp", ".c", ".h", ".hpp",
    ".rb", ".ex", ".exs", ".swift", ".php",
}


class CodeAnalyzer:
    """Analyzes project source code and builds a structured map.

    Currently supports Python AST analysis. Other languages get
    basic file-level info (line count, imports by regex).
    """

    def __init__(self, project_path: str) -> None:
        self._root = Path(project_path).resolve()

    def scan(self, scope: str = "") -> dict[str, ModuleInfo]:
        """Scan source files and return a map of file -> ModuleInfo."""
        modules: dict[str, ModuleInfo] = {}
        base = self._root / scope if scope else self._root
        base = base.resolve()
        if not str(base).startswith(str(self._root)):
            raise ValueError(f"Scope escapes project root: {scope}")

        if not base.exists():
            return modules

        for f in base.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in _SOURCE_EXTS:
                continue
            if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in f.parts):
                continue

            rel = str(f.relative_to(self._root)).replace("\\", "/")

            if f.stat().st_size > MAX_FILE_SIZE:
                _log.warning("Skipping %s: file too large (%d bytes)", rel, f.stat().st_size)
                continue

            if f.suffix == ".py":
                try:
                    info = self._analyze_python(f, rel)
                    modules[rel] = info
                except Exception as exc:
                    _log.warning("Failed to analyze %s: %s", rel, exc)
                    modules[rel] = ModuleInfo(
                        file=rel, docstring="", classes=[], functions=[],
                        imports=[], lines_of_code=0,
                    )
            else:
                # Basic info for non-Python files
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    modules[rel] = ModuleInfo(
                        file=rel, docstring="",
                        classes=[], functions=[], imports=[],
                        lines_of_code=len(text.splitlines()),
                    )
                except Exception as exc:
                    _log.warning("Failed to read %s: %s", rel, exc)

        _log.info("Scanned %d source files in %s", len(modules), base)
        return modules

    def _analyze_python(self, path: Path, rel: str) -> ModuleInfo:
        """Parse Python file with AST and extract structured info."""
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=rel)
        lines = source.splitlines()

        # Module docstring
        docstring = ast.get_docstring(tree) or ""

        # Imports
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        # Top-level classes and functions
        classes: list[ClassInfo] = []
        functions: list[FunctionInfo] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(self._extract_class(node, rel, lines))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(self._extract_function(node, rel, lines))

        return ModuleInfo(
            file=rel,
            docstring=docstring,
            classes=classes,
            functions=functions,
            imports=imports,
            lines_of_code=len(lines),
        )

    def _extract_class(self, node: ast.ClassDef, rel: str, lines: list[str]) -> ClassInfo:
        """Extract class info from AST node."""
        methods: list[FunctionInfo] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._extract_function(item, rel, lines))

        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(ast.unparse(base))

        return ClassInfo(
            name=node.name,
            file=rel,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=ast.get_docstring(node) or "",
            methods=methods,
            bases=bases,
            is_public=not node.name.startswith("_"),
        )

    def _extract_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
        rel: str, lines: list[str],
    ) -> FunctionInfo:
        """Extract function info from AST node."""
        # Build signature string
        try:
            sig = ast.unparse(node.args)
        except Exception:
            sig = "..."

        # Decorators
        decorators = []
        for dec in node.decorator_list:
            try:
                decorators.append(ast.unparse(dec))
            except Exception:
                decorators.append("?")

        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        returns = ""
        if node.returns:
            try:
                returns = f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass

        return FunctionInfo(
            name=node.name,
            file=rel,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            signature=f"{prefix}def {node.name}({sig}){returns}",
            docstring=ast.get_docstring(node) or "",
            is_public=not node.name.startswith("_"),
            decorators=decorators,
        )

    def get_public_api(self, modules: dict[str, ModuleInfo] | None = None) -> dict[str, ModuleInfo]:
        """Filter modules to only public API (public classes + functions)."""
        if modules is None:
            modules = self.scan()

        public: dict[str, ModuleInfo] = {}
        for path, mod in modules.items():
            pub_classes = [c for c in mod.get("classes", []) if c.get("is_public")]
            pub_funcs = [f for f in mod.get("functions", []) if f.get("is_public")]
            if pub_classes or pub_funcs:
                public[path] = ModuleInfo(
                    file=path,
                    docstring=mod.get("docstring", ""),
                    classes=pub_classes,
                    functions=pub_funcs,
                    imports=mod.get("imports", []),
                    lines_of_code=mod.get("lines_of_code", 0),
                )
        return public

    def get_undocumented(self, modules: dict[str, ModuleInfo] | None = None) -> list[dict]:
        """Find public functions/classes without docstrings."""
        if modules is None:
            modules = self.scan()

        undocumented = []
        for path, mod in modules.items():
            for cls in mod.get("classes", []):
                if cls.get("is_public") and not cls.get("docstring"):
                    undocumented.append({
                        "type": "class",
                        "name": cls.get("name", ""),
                        "file": path,
                        "line": cls.get("line_start", 0),
                    })
                for method in cls.get("methods", []):
                    if method.get("is_public") and not method.get("docstring"):
                        undocumented.append({
                            "type": "method",
                            "name": f"{cls.get('name', '')}.{method.get('name', '')}",
                            "file": path,
                            "line": method.get("line_start", 0),
                        })
            for func in mod.get("functions", []):
                if func.get("is_public") and not func.get("docstring"):
                    undocumented.append({
                        "type": "function",
                        "name": func.get("name", ""),
                        "file": path,
                        "line": func.get("line_start", 0),
                    })
        return undocumented
