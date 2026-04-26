"""Tests for DocVerifier."""

import pytest
from doc_swarm.code_analyzer import CodeAnalyzer
from doc_swarm.doc_verifier import DocVerifier


class TestDocVerifier:
    def test_finds_broken_source_file(self, sample_project, sample_docs):
        # sample docs reference src/mylib/core.py which exists — no issue there
        # But let's create a doc with bad source_file
        bad_doc = sample_docs / "api" / "bad.md"
        bad_doc.write_text("""---
title: Bad
source_file: src/mylib/nonexistent.py
---

# Bad doc
""")
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_docs))
        issues = verifier.verify_all(modules)

        source_issues = [i for i in issues if "source_file" in i.title.lower() and "nonexistent" in i.title]
        assert len(source_issues) >= 1

    def test_finds_broken_wikilinks(self, sample_project, sample_docs):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_docs))
        issues = verifier.verify_all(modules)

        wikilink_issues = [i for i in issues if "wikilink" in i.title.lower()]
        # core.md has [[missing_page]] which doesn't exist
        assert any("missing_page" in i.title for i in wikilink_issues)

    def test_finds_nonexistent_documented_function(self, sample_project, sample_docs):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_docs))
        issues = verifier.verify_all(modules)

        func_issues = [i for i in issues if "no longer exists" in i.title.lower()]
        # core.md lists nonexistent_function
        assert any("nonexistent_function" in i.title for i in func_issues)

    def test_finds_undocumented_modules(self, sample_project, sample_docs):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_docs))
        issues = verifier.verify_all(modules)

        undoc_issues = [i for i in issues if "undocumented" in i.title.lower()]
        # utils.py has public API but no doc page
        assert any("utils" in i.source_file for i in undoc_issues)

    def test_valid_code_block_no_issue(self, sample_project, sample_docs):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_docs))
        issues = verifier.verify_all(modules)

        # core.md has valid Python code block
        code_issues = [i for i in issues if "code block" in i.title.lower()]
        assert len(code_issues) == 0

    def test_invalid_code_block(self, sample_project, sample_docs):
        bad_doc = sample_docs / "api" / "badcode.md"
        bad_doc.write_text("""---
title: Bad Code
---

```python
def broken(
    # missing closing paren
```
""")
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_docs))
        issues = verifier.verify_all(modules)

        code_issues = [i for i in issues if "code block" in i.title.lower()]
        assert len(code_issues) >= 1

    def test_no_docs_directory(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        verifier = DocVerifier(str(sample_project), str(sample_project / "nonexistent_docs"))
        issues = verifier.verify_all(modules)
        # Should only have undocumented module issues
        assert all("undocumented" in i.title.lower() for i in issues)
