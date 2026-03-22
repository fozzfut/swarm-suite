"""Tests for DocGenerator."""

import pytest
from doc_swarm.code_analyzer import CodeAnalyzer
from doc_swarm.doc_generator import DocGenerator
from doc_swarm.models import DocType, DocStatus


class TestDocGenerator:
    def test_generate_api_page(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        gen = DocGenerator()

        core = [v for k, v in modules.items() if "core.py" in k]
        assert len(core) == 1
        core_path = [k for k in modules if "core.py" in k][0]

        page = gen.generate_api_page(core_path, core[0])
        assert page.doc_type == DocType.API
        assert page.status == DocStatus.DRAFT
        assert "Engine" in page.content
        assert "create_engine" in page.content
        assert "_internal_helper" not in page.content  # private, should be excluded

    def test_api_page_has_frontmatter(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        gen = DocGenerator()

        core_path = [k for k in modules if "core.py" in k][0]
        page = gen.generate_api_page(core_path, modules[core_path])

        md = page.to_markdown()
        assert md.startswith("---")
        assert "source_file:" in md
        assert "title:" in md

    def test_generate_index(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        public = analyzer.get_public_api(modules)
        gen = DocGenerator()

        pages = [gen.generate_api_page(p, m) for p, m in public.items()]
        index = gen.generate_index(pages)

        assert index.doc_type == DocType.INDEX
        assert "[[" in index.content  # has wikilinks
        assert "core" in index.content.lower()

    def test_generate_home(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        public = analyzer.get_public_api(modules)
        gen = DocGenerator()

        pages = [gen.generate_api_page(p, m) for p, m in public.items()]
        home = gen.generate_home(pages, "MyLib")

        assert "MyLib" in home.content
        assert "API Reference" in home.content

    def test_generate_coverage(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        gen = DocGenerator()

        coverage = gen.generate_coverage_report(modules, [])
        assert "Missing Documentation" in coverage.content
        assert "Coverage:" in coverage.content

    def test_coverage_with_docs(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        gen = DocGenerator()

        # Pass actual source file path instead of doc path
        coverage = gen.generate_coverage_report(modules, {"src/mylib/core.py"})
        assert "Documented" in coverage.content
