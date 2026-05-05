"""Tests for stack_registry — YAML-driven stack adapter discovery."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fix_swarm.regression_checker import _detect_test_command
from fix_swarm.stack_registry import StackAdapter, StackRegistry


# ─── Built-in registry ─────────────────────────────────────────────────────


def test_builtin_registry_loads_all_stacks() -> None:
    reg = StackRegistry()
    names = {a.name for a in reg.all()}
    expected = {"python", "node", "go", "rust", "c-cmake", "c-make", "dotnet"}
    assert expected.issubset(names), f"missing: {expected - names}"


def test_python_substitution() -> None:
    reg = StackRegistry()
    py = reg.get("python")
    assert py is not None
    assert "{python}" in py.test_command  # source preserves placeholder
    resolved = py.resolved_command()
    assert sys.executable in resolved
    assert "{python}" not in resolved


# ─── Detection ──────────────────────────────────────────────────────────────


def _touch(p: Path, content: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_detect_python_via_pyproject(tmp_path: Path) -> None:
    _touch(tmp_path / "pyproject.toml")
    a = StackRegistry().detect(tmp_path)
    assert a is not None and a.name == "python"


def test_detect_rust_via_cargo_toml(tmp_path: Path) -> None:
    _touch(tmp_path / "Cargo.toml")
    a = StackRegistry().detect(tmp_path)
    assert a is not None and a.name == "rust"


def test_detect_c_cmake(tmp_path: Path) -> None:
    _touch(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
    a = StackRegistry().detect(tmp_path)
    assert a is not None and a.name == "c-cmake"


def test_detect_c_make_only(tmp_path: Path) -> None:
    """Plain Makefile without CMakeLists -> c-make adapter."""
    _touch(tmp_path / "Makefile", "all:\n\techo build\n")
    a = StackRegistry().detect(tmp_path)
    assert a is not None and a.name == "c-make"


def test_detect_dotnet_via_csproj_glob(tmp_path: Path) -> None:
    _touch(tmp_path / "MyApp.csproj", "<Project></Project>")
    a = StackRegistry().detect(tmp_path)
    assert a is not None and a.name == "dotnet"


def test_detect_returns_none_on_unknown_project(tmp_path: Path) -> None:
    a = StackRegistry().detect(tmp_path)
    assert a is None


def test_detect_test_command_resolves_python(tmp_path: Path) -> None:
    _touch(tmp_path / "pyproject.toml")
    cmd = StackRegistry().detect_test_command(tmp_path)
    assert cmd
    assert sys.executable in cmd
    assert "pytest" in cmd


def test_detect_test_command_for_rust(tmp_path: Path) -> None:
    _touch(tmp_path / "Cargo.toml")
    cmd = StackRegistry().detect_test_command(tmp_path)
    assert cmd == "cargo test --quiet"


def test_detect_test_command_for_c_cmake(tmp_path: Path) -> None:
    _touch(tmp_path / "CMakeLists.txt")
    cmd = StackRegistry().detect_test_command(tmp_path)
    assert "cmake" in cmd
    assert "ctest" in cmd


# ─── Custom-dir override (drop a YAML to add a stack) ──────────────────────


def test_custom_dir_adds_new_stack(tmp_path: Path) -> None:
    """User can add a Zig stack adapter without touching code."""
    custom = tmp_path / "stacks"
    custom.mkdir()
    _touch(custom / "zig.yaml",
           "name: zig\n"
           "detect_files: [build.zig]\n"
           "test_command: 'zig build test'\n"
           "file_extensions: ['.zig']\n")
    reg = StackRegistry(custom_dirs=[custom])
    zig = reg.get("zig")
    assert zig is not None
    assert zig.test_command == "zig build test"


def test_custom_dir_overrides_builtin_by_name(tmp_path: Path) -> None:
    """Custom dir wins on name collision."""
    custom = tmp_path / "stacks"
    custom.mkdir()
    _touch(custom / "rust.yaml",
           "name: rust\n"
           "detect_files: [Cargo.toml]\n"
           "test_command: 'cargo nextest run'\n")  # nextest replaces default
    reg = StackRegistry(custom_dirs=[custom])
    rust = reg.get("rust")
    assert rust is not None
    assert rust.test_command == "cargo nextest run"


def test_custom_dir_only_isolates_loading(tmp_path: Path) -> None:
    """Empty builtin_dir means only custom dir contributes."""
    only = tmp_path / "only"
    only.mkdir()
    _touch(only / "x.yaml", "name: x\ndetect_files: [.x]\ntest_command: 'echo x'\n")
    reg = StackRegistry(builtin_dir=tmp_path / "missing", custom_dirs=[only])
    assert {a.name for a in reg.all()} == {"x"}


def test_malformed_yaml_skipped(tmp_path: Path) -> None:
    custom = tmp_path / "stacks"
    custom.mkdir()
    _touch(custom / "good.yaml",
           "name: good\ndetect_files: [.x]\ntest_command: 'echo'\n")
    _touch(custom / "broken.yaml", "::: not valid YAML :::\n")
    reg = StackRegistry(builtin_dir=tmp_path / "missing", custom_dirs=[custom])
    names = {a.name for a in reg.all()}
    assert "good" in names
    assert "broken" not in names


# ─── End-to-end: regression_checker uses the registry ──────────────────────


def test_regression_checker_uses_registry_for_python(tmp_path: Path) -> None:
    _touch(tmp_path / "pyproject.toml")
    cmd = _detect_test_command(tmp_path)
    assert "pytest" in cmd
    assert sys.executable in cmd


def test_regression_checker_uses_registry_for_rust(tmp_path: Path) -> None:
    _touch(tmp_path / "Cargo.toml")
    cmd = _detect_test_command(tmp_path)
    assert cmd == "cargo test --quiet"


def test_regression_checker_uses_registry_for_c_cmake(tmp_path: Path) -> None:
    _touch(tmp_path / "CMakeLists.txt")
    cmd = _detect_test_command(tmp_path)
    assert "cmake" in cmd and "ctest" in cmd


def test_regression_checker_falls_back_to_pytest_for_loose_tests_dir(
    tmp_path: Path,
) -> None:
    """No build manifest, but a tests/ dir → fallback pytest detection."""
    (tmp_path / "tests").mkdir()
    cmd = _detect_test_command(tmp_path)
    assert "pytest" in cmd


def test_regression_checker_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    assert _detect_test_command(tmp_path) == ""
