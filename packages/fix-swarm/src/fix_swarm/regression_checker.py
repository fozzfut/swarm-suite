"""Regression detection: syntax check, test suite, re-scan for new issues."""

import ast
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger("fix_swarm.regression")


@dataclass
class TestResult:
    command: str = ""
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    passed: bool = True
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "passed": self.passed,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class RegressionReport:
    syntax_ok: bool = True
    syntax_errors: list[dict] = field(default_factory=list)
    tests_before: dict = field(default_factory=dict)
    tests_after: dict = field(default_factory=dict)
    test_regression: bool = False
    new_findings: list[dict] = field(default_factory=list)
    overall_ok: bool = True

    def to_dict(self) -> dict:
        return {
            "syntax_ok": self.syntax_ok,
            "syntax_errors": self.syntax_errors,
            "tests_before": self.tests_before,
            "tests_after": self.tests_after,
            "test_regression": self.test_regression,
            "new_findings": self.new_findings,
            "overall_ok": self.overall_ok,
        }


def check_syntax(files: list[str], base_dir: str = ".") -> list[dict]:
    """Check Python files for syntax errors. Returns list of {file, error}."""
    base = Path(base_dir)
    errors = []
    for file_path in files:
        fp = base / file_path
        if not fp.is_file() or fp.suffix != ".py":
            continue
        try:
            source = fp.read_text(encoding="utf-8", errors="ignore")
            ast.parse(source, filename=str(fp))
        except SyntaxError as exc:
            errors.append({
                "file": file_path,
                "error": f"SyntaxError: {exc.msg} (line {exc.lineno})",
            })
    return errors


def run_tests(test_command: str = "", base_dir: str = ".", timeout: int = 300) -> TestResult:
    """Run project test suite. Auto-detects pytest/npm/go/cargo if no command given.

    Security: User-provided commands are parsed via :func:`shlex.split` and run
    with ``shell=False``.  Auto-detected commands use ``shell=True`` for
    Windows compatibility (npm/go/cargo/dotnet are batch scripts on Windows).
    Callers that expose ``test_command`` to untrusted input should validate or
    restrict the value before passing it here.
    """
    base = Path(base_dir)

    user_provided = bool(test_command)
    if not test_command:
        test_command = _detect_test_command(base)

    if not test_command:
        return TestResult(
            command="(none detected)",
            passed=True,
            stdout="No test framework detected. Skipping.",
        )

    if user_provided:
        # User command: use shlex for safety, shell=False
        import shlex
        import platform
        try:
            args = shlex.split(test_command, posix=(platform.system() != 'Windows'))
        except ValueError:
            return TestResult(
                command=test_command,
                exit_code=-1,
                stderr="Invalid command syntax",
                passed=False,
            )
        use_shell = False
        cmd = args
    else:
        # Auto-detected: safe known commands, use shell=True for Windows compat
        # (npm, go, cargo, dotnet are batch scripts on Windows)
        use_shell = True
        cmd = test_command

    start = time.time()
    try:
        result = subprocess.run(
            cmd, shell=use_shell, cwd=str(base),
            capture_output=True, text=True, timeout=timeout,
        )
        duration = time.time() - start
        return TestResult(
            command=test_command,
            exit_code=result.returncode,
            stdout=result.stdout[-2000:],
            stderr=result.stderr[-2000:],
            passed=(result.returncode == 0),
            duration_seconds=round(duration, 2),
        )
    except subprocess.TimeoutExpired:
        return TestResult(command=test_command, exit_code=-1,
                         stderr=f"Timed out after {timeout}s", passed=False,
                         duration_seconds=float(timeout))
    except Exception as exc:
        return TestResult(command=test_command, exit_code=-1,
                         stderr=str(exc), passed=False)


def _detect_test_command(base: Path) -> str:
    """Auto-detect test command for a project."""
    # Python
    if (base / "pyproject.toml").exists() or (base / "pytest.ini").exists():
        return f"{sys.executable} -m pytest --tb=short -q"
    if (base / "tests").is_dir() or (base / "test").is_dir():
        return f"{sys.executable} -m pytest --tb=short -q"
    # Node
    if (base / "package.json").exists():
        return "npm test --if-present"
    # Go
    if (base / "go.mod").exists():
        return "go test ./... -short"
    # Rust
    if (base / "Cargo.toml").exists():
        return "cargo test --quiet"
    # .NET
    if any(base.glob("*.csproj")) or any(base.glob("*.sln")):
        return "dotnet test --verbosity minimal"
    return ""


def rescan_files(files: list[str], base_dir: str = ".") -> list[dict]:
    """Quick re-scan of modified Python files for regression indicators."""
    base = Path(base_dir)
    findings = []
    for file_path in files:
        fp = base / file_path
        if not fp.is_file() or fp.suffix != ".py":
            continue
        try:
            source = fp.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            continue  # caught by check_syntax

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Check for empty functions (possible bad fix)
                body = [n for n in node.body
                        if not (isinstance(n, ast.Expr) and isinstance(getattr(n, 'value', None), ast.Constant))]
                if not body or (len(body) == 1 and isinstance(body[0], ast.Pass)):
                    decs = []
                    for d in node.decorator_list:
                        try:
                            decs.append(ast.unparse(d))
                        except Exception:
                            pass
                    if not any('abstract' in d.lower() for d in decs):
                        findings.append({
                            "file": file_path,
                            "line_start": node.lineno,
                            "severity": "medium",
                            "title": f"Empty function after fix: {node.name}",
                            "category": "regression",
                        })
    return findings


def check_regression(
    modified_files: list[str],
    base_dir: str = ".",
    test_command: str = "",
    tests_before: Optional[dict] = None,
) -> RegressionReport:
    """Full regression check: syntax + tests + re-scan."""
    report = RegressionReport()

    # 1. Syntax
    syntax_errors = check_syntax(modified_files, base_dir)
    if syntax_errors:
        report.syntax_ok = False
        report.syntax_errors = syntax_errors
        report.overall_ok = False

    # 2. Tests
    tests_after = run_tests(test_command, base_dir)
    report.tests_after = tests_after.to_dict()
    if tests_before:
        report.tests_before = tests_before

    if tests_before and tests_before.get("passed") and not tests_after.passed:
        report.test_regression = True
        report.overall_ok = False
    elif not tests_after.passed and tests_after.command != "(none detected)":
        report.test_regression = True
        report.overall_ok = False

    # 3. Re-scan
    new_findings = rescan_files(modified_files, base_dir)
    report.new_findings = new_findings
    high_sev = [f for f in new_findings if f.get("severity") in ("critical", "high")]
    if high_sev:
        report.overall_ok = False

    return report
