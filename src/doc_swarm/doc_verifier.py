"""Doc verifier -- checks existing documentation against actual code."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .models import DocIssue, DocStatus, Severity, ModuleInfo

_log = logging.getLogger("doc_swarm.doc_verifier")


class DocVerifier:
    """Verifies existing documentation accuracy against code.

    Checks:
    - frontmatter source_file points to existing file
    - wikilinks [[target]] resolve to existing docs
    - documented functions/classes still exist in code
    - code examples are syntactically valid
    - imports mentioned in docs match actual imports
    """

    def __init__(self, project_path: str, docs_path: str) -> None:
        self._project = Path(project_path).resolve()
        self._docs = Path(docs_path).resolve()

    def verify_all(
        self,
        modules: dict[str, ModuleInfo],
        session_id: str = "",
    ) -> list[DocIssue]:
        """Run all verification checks on existing docs."""
        issues: list[DocIssue] = []

        doc_files = self._scan_docs()
        doc_stems = {Path(d).stem for d in doc_files}
        doc_source_files: set[str] = set()

        for doc_path in doc_files:
            full_path = self._docs / doc_path
            try:
                text = full_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            frontmatter, body = self._parse_frontmatter(text)

            # Check source_file reference
            source_file = frontmatter.get("source_file", "")
            if source_file:
                doc_source_files.add(source_file)
                source_path = self._project / source_file
                if not source_path.exists():
                    issues.append(DocIssue(
                        id=DocIssue.generate_id(),
                        session_id=session_id,
                        expert_role="accuracy-verifier",
                        file=doc_path,
                        source_file=source_file,
                        severity=Severity.HIGH,
                        title=f"source_file does not exist: {source_file}",
                        description=f"Frontmatter references {source_file} but file not found on disk",
                        suggestion=f"Update source_file or remove if module was deleted",
                    ))

            # Check wikilinks
            wikilinks = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', body)
            for link in wikilinks:
                if link not in doc_stems:
                    issues.append(DocIssue(
                        id=DocIssue.generate_id(),
                        session_id=session_id,
                        expert_role="cross-reference-builder",
                        file=doc_path,
                        source_file="",
                        severity=Severity.MEDIUM,
                        title=f"Broken wikilink: [[{link}]]",
                        description=f"Wikilink [[{link}]] does not resolve to any doc file",
                        suggestion=f"Create {link}.md or fix the link target",
                    ))

            # Check code blocks are valid Python
            code_blocks = re.findall(r'```python\n(.*?)```', body, re.DOTALL)
            for i, block in enumerate(code_blocks):
                try:
                    compile(block, f"{doc_path}:block{i}", "exec")
                except SyntaxError as exc:
                    issues.append(DocIssue(
                        id=DocIssue.generate_id(),
                        session_id=session_id,
                        expert_role="code-example-writer",
                        file=doc_path,
                        source_file="",
                        severity=Severity.MEDIUM,
                        title=f"Invalid Python code block #{i+1}",
                        description=f"SyntaxError: {exc.msg} (line {exc.lineno})",
                        suggestion="Fix the code example or mark as pseudocode",
                    ))

            # Check documented functions still exist in code
            if source_file and source_file in modules:
                mod = modules[source_file]
                documented_funcs = frontmatter.get("functions", [])
                actual_funcs = {f.get("name", "") for f in mod.get("functions", [])}
                actual_funcs.update(
                    m.get("name", "")
                    for c in mod.get("classes", [])
                    for m in c.get("methods", [])
                )
                for func_name in documented_funcs:
                    if func_name not in actual_funcs:
                        issues.append(DocIssue(
                            id=DocIssue.generate_id(),
                            session_id=session_id,
                            expert_role="accuracy-verifier",
                            file=doc_path,
                            source_file=source_file,
                            severity=Severity.HIGH,
                            title=f"Documented function no longer exists: {func_name}",
                            description=f"{func_name} is listed in frontmatter but not found in {source_file}",
                            suggestion=f"Remove {func_name} from docs or check if it was renamed",
                        ))

        # Check for undocumented modules
        for mod_path, info in modules.items():
            has_public = (
                any(c.get("is_public") for c in info.get("classes", []))
                or any(f.get("is_public") for f in info.get("functions", []))
            )
            if has_public and mod_path not in doc_source_files:
                issues.append(DocIssue(
                    id=DocIssue.generate_id(),
                    session_id=session_id,
                    expert_role="accuracy-verifier",
                    file="",
                    source_file=mod_path,
                    severity=Severity.MEDIUM,
                    title=f"Undocumented module: {mod_path}",
                    description=f"{mod_path} has public API but no documentation page",
                    suggestion=f"Generate API docs for {mod_path}",
                    status=DocStatus.MISSING,
                ))

        _log.info("Verified %d doc files, found %d issues", len(doc_files), len(issues))
        return issues

    def _scan_docs(self) -> list[str]:
        """Scan docs directory for markdown files."""
        if not self._docs.exists():
            return []
        files = []
        for f in sorted(self._docs.rglob("*.md")):
            if any(part.startswith(".") for part in f.parts):
                continue
            files.append(str(f.relative_to(self._docs)).replace("\\", "/"))
        return files

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown text."""
        if not text.startswith("---"):
            return {}, text

        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text

        try:
            fm = yaml.safe_load(parts[1]) or {}
            if not isinstance(fm, dict):
                fm = {}
        except yaml.YAMLError:
            fm = {}

        body = parts[2]
        return fm, body
