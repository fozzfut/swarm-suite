"""Unified AST scanner -- merges DocSwarm (detail) and ArchSwarm (metrics)."""

from __future__ import annotations

import ast
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    ClassInfo,
    CouplingMetrics,
    FunctionInfo,
    ProjectCodeMap,
    UnifiedModuleInfo,
)

_log = logging.getLogger("swarm_kb.code_map.scanner")

_DEFAULT_SKIP_DIRS = {
    "node_modules", ".venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".tox",
    ".eggs", "site-packages",
}

_DEFAULT_SOURCE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".kt",
    ".cs", ".cpp", ".c", ".h", ".hpp",
    ".rb", ".ex", ".exs", ".swift", ".php",
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def scan_project(
    project_path: str | Path,
    scope: str = "",
    skip_dirs: set[str] | None = None,
    source_exts: set[str] | None = None,
    max_file_size: int = MAX_FILE_SIZE,
) -> ProjectCodeMap:
    """Scan a project and return a unified ProjectCodeMap.

    Combines DocSwarm-style detail (signatures, docstrings, line ranges)
    with ArchSwarm-style metrics (coupling, complexity, dependency graph).
    """
    root = Path(project_path).resolve()
    scan_root = root / scope if scope else root

    if skip_dirs is None:
        skip_dirs = _DEFAULT_SKIP_DIRS
    if source_exts is None:
        source_exts = _DEFAULT_SOURCE_EXTS

    code_map = ProjectCodeMap(
        root=str(root),
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )

    if not scan_root.is_dir():
        return code_map

    for fp in sorted(scan_root.rglob("*")):
        if not fp.is_file():
            continue
        if fp.suffix not in source_exts:
            continue

        try:
            rel_parts = fp.relative_to(root).parts
        except ValueError:
            continue
        if any(part in skip_dirs or part.endswith(".egg-info") for part in rel_parts):
            continue

        rel = str(fp.relative_to(root)).replace("\\", "/")

        try:
            file_size = fp.stat().st_size
        except OSError:
            continue
        if file_size > max_file_size:
            _log.warning("Skipping %s: too large (%d bytes)", rel, file_size)
            continue

        if fp.suffix == ".py":
            try:
                mod = _analyze_python(fp, rel, root)
                code_map.modules.append(mod)
                code_map.dependency_graph[mod.name] = list(mod.imports)
                code_map.complexity_scores[mod.name] = _estimate_complexity_from_file(fp)
                hierarchy = _extract_class_hierarchy_from_file(fp)
                for cls_name, bases in hierarchy.items():
                    code_map.class_hierarchy[f"{mod.name}.{cls_name}"] = bases
            except Exception as exc:
                _log.warning("Failed to analyze %s: %s", rel, exc)
                code_map.modules.append(UnifiedModuleInfo(file=rel))
        else:
            # Basic info for non-Python
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
                code_map.modules.append(UnifiedModuleInfo(
                    file=rel,
                    lines_of_code=len(text.splitlines()),
                ))
            except Exception as exc:
                _log.warning("Failed to read %s: %s", rel, exc)

    # Compute coupling metrics
    code_map.coupling = _compute_coupling(code_map)

    _log.info("Scanned %d modules in %s", len(code_map.modules), scan_root)
    return code_map


# -- Python AST analysis (merged from DocSwarm + ArchSwarm) -------------------


def _analyze_python(path: Path, rel: str, root: Path) -> UnifiedModuleInfo:
    """Parse a Python file and extract full module info."""
    source = path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(source, filename=rel)
    lines = source.splitlines()

    # Module name (from ArchSwarm)
    mod_name = rel.replace("/", ".").replace("\\", ".").removesuffix(".py").removesuffix(".__init__")
    if mod_name.startswith("src."):
        mod_name = mod_name[4:]

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

    # Top-level classes and functions (DocSwarm-style detail)
    classes: list[ClassInfo] = []
    functions: list[FunctionInfo] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(_extract_class(node, rel))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_extract_function(node, rel))

    return UnifiedModuleInfo(
        file=rel,
        name=mod_name,
        docstring=docstring,
        classes=classes,
        functions=functions,
        imports=imports,
        lines_of_code=len(lines),
    )


def _extract_class(node: ast.ClassDef, rel: str) -> ClassInfo:
    """Extract class info including methods, bases, docstring."""
    methods: list[FunctionInfo] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_extract_function(item, rel))

    bases = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(ast.unparse(base))
        else:
            try:
                bases.append(ast.unparse(base))
            except Exception:
                pass

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


def _extract_function(node: ast.FunctionDef | ast.AsyncFunctionDef, rel: str) -> FunctionInfo:
    """Extract function info with signature, decorators, docstring."""
    try:
        sig = ast.unparse(node.args)
    except Exception:
        sig = "..."

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


# -- ArchSwarm-style metrics --------------------------------------------------


def _estimate_complexity_from_file(path: Path) -> int:
    """Rough cyclomatic-complexity approximation for a Python file."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError):
        return 1

    complexity = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)):
            complexity += 1
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            complexity += 1
        elif isinstance(node, ast.While):
            complexity += 1
        elif isinstance(node, ast.ExceptHandler):
            complexity += 1
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            complexity += len(node.values) - 1
    return complexity


def _extract_class_hierarchy_from_file(path: Path) -> dict[str, list[str]]:
    """Map class -> base class names from a Python file."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError):
        return {}

    hierarchy: dict[str, list[str]] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    try:
                        bases.append(ast.unparse(base))
                    except Exception:
                        pass
            if bases:
                hierarchy[node.name] = bases
    return hierarchy


def _compute_coupling(code_map: ProjectCodeMap) -> list[CouplingMetrics]:
    """Compute coupling metrics for all modules in the code map."""
    all_names = {m.name for m in code_map.modules if m.name}
    coupling_map: dict[str, CouplingMetrics] = {
        name: CouplingMetrics(module=name) for name in all_names
    }

    sorted_modules = sorted(all_names, key=len, reverse=True)

    for mod in code_map.modules:
        if not mod.name:
            continue
        seen: set[str] = set()
        for imp in mod.imports:
            for target in sorted_modules:
                if imp == target or imp.startswith(target + "."):
                    if target not in seen and target != mod.name:
                        seen.add(target)
                        coupling_map[mod.name].efferent += 1
                        coupling_map[target].afferent += 1
                    break
    return list(coupling_map.values())
