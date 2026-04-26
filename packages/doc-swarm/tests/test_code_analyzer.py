"""Tests for CodeAnalyzer."""

import pytest
from doc_swarm.code_analyzer import CodeAnalyzer


class TestCodeAnalyzer:
    def test_scan_finds_python_files(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        assert len(modules) >= 2
        assert any("core.py" in k for k in modules)
        assert any("utils.py" in k for k in modules)

    def test_scan_extracts_classes(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        classes = core.get("classes", [])
        assert len(classes) == 1
        assert classes[0]["name"] == "Engine"
        assert classes[0]["is_public"] is True

    def test_scan_extracts_functions(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        funcs = core.get("functions", [])
        pub = [f for f in funcs if f.get("is_public")]
        priv = [f for f in funcs if not f.get("is_public")]
        assert any(f["name"] == "create_engine" for f in pub)
        assert any(f["name"] == "_internal_helper" for f in priv)

    def test_scan_extracts_docstrings(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        assert "Core module" in core.get("docstring", "")
        cls = core["classes"][0]
        assert "processing engine" in cls.get("docstring", "").lower()

    def test_scan_extracts_imports(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        imports = core.get("imports", [])
        assert "threading" in imports

    def test_scan_extracts_methods(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        cls = core["classes"][0]
        methods = cls.get("methods", [])
        names = [m["name"] for m in methods]
        assert "process" in names
        assert "__init__" in names

    def test_get_public_api(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        public = analyzer.get_public_api(modules)
        # Should have core.py and utils.py (both have public symbols)
        assert len(public) >= 2

    def test_get_undocumented(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        undoc = analyzer.get_undocumented(modules)
        # validate_input has a one-liner docstring, so it should be documented
        # _internal_helper is private, should not appear
        names = [u["name"] for u in undoc]
        assert "_internal_helper" not in names

    def test_empty_project(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        analyzer = CodeAnalyzer(str(empty))
        assert analyzer.scan() == {}

    def test_line_counts(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        for info in modules.values():
            assert info.get("lines_of_code", 0) > 0

    def test_function_signatures(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        funcs = core.get("functions", [])
        create = [f for f in funcs if f["name"] == "create_engine"][0]
        assert "config" in create.get("signature", "")

    def test_class_bases(self, sample_project):
        analyzer = CodeAnalyzer(str(sample_project))
        modules = analyzer.scan("src/")
        core = [v for k, v in modules.items() if "core.py" in k][0]
        cls = core["classes"][0]
        # Engine has no bases
        assert cls.get("bases", []) == []
