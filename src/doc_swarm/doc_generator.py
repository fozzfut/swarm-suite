"""Doc generator -- produces markdown documentation from code analysis."""

from __future__ import annotations

import logging
from pathlib import Path

from typing import Any

from .models import DocPage, DocType, DocStatus, ModuleInfo

_log = logging.getLogger("doc_swarm.doc_generator")


class DocGenerator:
    """Generates documentation pages from code analysis results.

    Produces Obsidian-compatible markdown with YAML frontmatter
    and wikilinks for cross-referencing.
    """

    def generate_api_page(self, module_path: str, info: ModuleInfo) -> DocPage:
        """Generate an API reference page for a module."""
        # Convert src/pkg/utils.py -> api/src-pkg-utils.md to avoid collisions
        safe_name = module_path.replace("/", "-").replace("\\", "-")
        if safe_name.endswith(".py"):
            safe_name = safe_name[:-3]
        title = self._title_from_path(module_path)

        lines: list[str] = []
        lines.append(f"# {title}\n")

        # Module docstring
        docstring = info.get("docstring", "")
        if docstring:
            lines.append(f"{docstring}\n")

        lines.append(f"**Source:** `{module_path}` | **Lines:** {info.get('lines_of_code', 0)}\n")

        # Imports summary
        imports = info.get("imports", [])
        if imports:
            lines.append("## Dependencies\n")
            for imp in sorted(set(imports)):
                lines.append(f"- `{imp}`")
            lines.append("")

        # Classes
        classes = info.get("classes", [])
        if classes:
            lines.append("## Classes\n")
            for cls in classes:
                self._render_class(cls, lines)

        # Functions
        functions = info.get("functions", [])
        if functions:
            lines.append("## Functions\n")
            for func in functions:
                self._render_function(func, lines)

        return DocPage(
            path=f"api/{safe_name}.md",
            doc_type=DocType.API,
            title=title,
            source_files=[module_path],
            frontmatter={
                "source_file": module_path,
                "lines_of_code": info.get("lines_of_code", 0),
                "classes": [c.get("name", "") for c in classes if c.get("is_public")],
                "functions": [f.get("name", "") for f in functions if f.get("is_public")],
            },
            content="\n".join(lines),
            status=DocStatus.DRAFT,
            generated_by="api-mapper",
        )

    def generate_index(self, pages: list[DocPage]) -> DocPage:
        """Generate an INDEX.md with keyword-to-file mapping for RAG."""
        lines = ["# Documentation Index\n"]
        lines.append("Keyword-to-file mapping for AI assistant retrieval.\n")

        # Group by type
        by_type: dict[str, list[DocPage]] = {}
        for page in pages:
            by_type.setdefault(page.doc_type.value, []).append(page)

        for doc_type, type_pages in sorted(by_type.items()):
            lines.append(f"## {doc_type.title()}\n")
            lines.append("| File | Title | Source | Keywords |")
            lines.append("|------|-------|--------|----------|")
            for page in sorted(type_pages, key=lambda p: p.path):
                keywords = self._extract_keywords(page)
                source = ", ".join(page.source_files[:3])
                lines.append(
                    f"| [[{Path(page.path).stem}]] | {page.title} | `{source}` | {', '.join(keywords)} |"
                )
            lines.append("")

        _log.info("Generated index with %d pages", len(pages))
        return DocPage(
            path="INDEX.md",
            doc_type=DocType.INDEX,
            title="Documentation Index",
            content="\n".join(lines),
            status=DocStatus.DRAFT,
            generated_by="cross-reference-builder",
        )

    def generate_home(self, pages: list[DocPage], project_name: str = "") -> DocPage:
        """Generate a HOME.md entry point."""
        lines = [f"# {project_name or 'Documentation'}\n"]

        # Quick links by type
        api_pages = [p for p in pages if p.doc_type == DocType.API]
        guide_pages = [p for p in pages if p.doc_type == DocType.GUIDE]
        arch_pages = [p for p in pages if p.doc_type == DocType.ARCHITECTURE]
        ref_pages = [p for p in pages if p.doc_type == DocType.REFERENCE]

        if api_pages:
            lines.append("## API Reference\n")
            for p in sorted(api_pages, key=lambda x: x.path):
                lines.append(f"- [[{Path(p.path).stem}]] — {p.title}")
            lines.append("")

        if guide_pages:
            lines.append("## Guides\n")
            for p in sorted(guide_pages, key=lambda x: x.path):
                lines.append(f"- [[{Path(p.path).stem}]] — {p.title}")
            lines.append("")

        if arch_pages:
            lines.append("## Architecture\n")
            for p in sorted(arch_pages, key=lambda x: x.path):
                lines.append(f"- [[{Path(p.path).stem}]] — {p.title}")
            lines.append("")

        if ref_pages:
            lines.append("## Reference\n")
            for p in sorted(ref_pages, key=lambda x: x.path):
                lines.append(f"- [[{Path(p.path).stem}]] — {p.title}")
            lines.append("")

        lines.append("## Index\n")
        lines.append("- [[INDEX]] — Full keyword-to-file mapping for AI assistants\n")

        return DocPage(
            path="HOME.md",
            doc_type=DocType.INDEX,
            title=f"{project_name or 'Project'} Documentation",
            content="\n".join(lines),
            status=DocStatus.DRAFT,
            generated_by="cross-reference-builder",
        )

    def generate_coverage_report(
        self,
        modules: dict[str, ModuleInfo],
        documented_source_files: set[str] | list[str],
    ) -> DocPage:
        """Generate a COVERAGE.md showing what's documented and what's not."""
        lines = ["# Documentation Coverage\n"]

        documented = set(documented_source_files)

        covered = []
        missing = []
        for mod_path, info in sorted(modules.items()):
            has_public = (
                any(c.get("is_public") for c in info.get("classes", []))
                or any(f.get("is_public") for f in info.get("functions", []))
            )
            if not has_public:
                continue
            if mod_path in documented:
                covered.append(mod_path)
            else:
                missing.append(mod_path)

        total = len(covered) + len(missing)
        pct = (len(covered) / total * 100) if total else 0

        lines.append(f"**Coverage: {len(covered)}/{total} modules ({pct:.0f}%)**\n")

        if missing:
            lines.append("## Missing Documentation\n")
            for m in missing:
                lines.append(f"- `{m}` — needs API docs")
            lines.append("")

        if covered:
            lines.append("## Documented\n")
            for m in covered:
                lines.append(f"- `{m}` — [[{Path(m).stem}]]")
            lines.append("")

        return DocPage(
            path="meta/COVERAGE.md",
            doc_type=DocType.REFERENCE,
            title="Documentation Coverage",
            content="\n".join(lines),
            status=DocStatus.DRAFT,
            generated_by="accuracy-verifier",
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _render_class(self, cls: Any, lines: list[str]) -> None:
        name = cls.get("name", "unknown")
        is_public = cls.get("is_public", True)
        if not is_public:
            return

        bases = cls.get("bases", [])
        bases_str = f"({', '.join(bases)})" if bases else ""
        lines.append(f"### `class {name}{bases_str}`\n")

        docstring = cls.get("docstring", "")
        if docstring:
            lines.append(f"{docstring}\n")

        lines.append(f"**Lines:** {cls.get('line_start', '?')}-{cls.get('line_end', '?')}\n")

        methods = cls.get("methods", [])
        public_methods = [m for m in methods if m.get("is_public")]
        if public_methods:
            lines.append("**Methods:**\n")
            for m in public_methods:
                sig = m.get("signature", m.get("name", "unknown"))
                doc = m.get("docstring", "")
                first_line = doc.split("\n")[0] if doc else ""
                lines.append(f"- `{sig}`{' — ' + first_line if first_line else ''}")
            lines.append("")

    def _render_function(self, func: Any, lines: list[str]) -> None:
        if not func.get("is_public", True):
            return

        sig = func.get("signature", func.get("name", "unknown"))
        lines.append(f"### `{sig}`\n")

        docstring = func.get("docstring", "")
        if docstring:
            lines.append(f"{docstring}\n")

        decorators = func.get("decorators", [])
        if decorators:
            lines.append(f"**Decorators:** {', '.join(f'`@{d}`' for d in decorators)}\n")

        lines.append(f"**Lines:** {func.get('line_start', '?')}-{func.get('line_end', '?')}\n")

    def _title_from_path(self, path: str) -> str:
        stem = Path(path).stem
        return stem.replace("_", " ").replace("-", " ").title()

    def _extract_keywords(self, page: DocPage) -> list[str]:
        keywords = []
        # From title
        keywords.extend(page.title.lower().split())
        # From frontmatter
        for cls_name in page.frontmatter.get("classes", []):
            keywords.append(cls_name.lower())
        for func_name in page.frontmatter.get("functions", []):
            keywords.append(func_name.lower())
        # Deduplicate
        return sorted(set(keywords))[:10]
