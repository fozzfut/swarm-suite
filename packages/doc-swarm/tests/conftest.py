import pytest
from pathlib import Path


@pytest.fixture
def sample_project(tmp_path):
    """Create a minimal Python project for testing."""
    src = tmp_path / "src" / "mylib"
    src.mkdir(parents=True)

    (src / "__init__.py").write_text('"""MyLib package."""\n\n__version__ = "1.0.0"\n')

    (src / "core.py").write_text('''"""Core module with main logic."""

import threading
from typing import Optional


class Engine:
    """Main processing engine.

    Handles data processing with thread safety.
    """

    def __init__(self, config: dict) -> None:
        """Initialize engine with config."""
        self._config = config
        self._lock = threading.Lock()

    def process(self, data: list[str]) -> list[str]:
        """Process a list of data items.

        Args:
            data: Input data items.

        Returns:
            Processed items.
        """
        with self._lock:
            return [self._transform(item) for item in data]

    def _transform(self, item: str) -> str:
        """Internal transform (private)."""
        return item.upper()


def create_engine(config: Optional[dict] = None) -> Engine:
    """Factory function to create an Engine.

    Args:
        config: Optional configuration dict.

    Returns:
        Configured Engine instance.
    """
    return Engine(config or {})


def _internal_helper() -> None:
    """This is private and should not appear in docs."""
    pass
''')

    (src / "utils.py").write_text('''"""Utility functions."""


def format_output(items: list[str], separator: str = ", ") -> str:
    """Format items as a single string.

    Args:
        items: List of strings to join.
        separator: Separator between items.

    Returns:
        Joined string.
    """
    return separator.join(items)


def validate_input(data: str) -> bool:
    """Check if input data is valid."""
    return bool(data and data.strip())
''')

    # Tests dir
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text("def test_engine():\n    pass\n")

    return tmp_path


@pytest.fixture
def sample_docs(tmp_path, sample_project):
    """Create sample docs directory with some existing docs."""
    docs = sample_project / "docs"
    docs.mkdir()
    api = docs / "api"
    api.mkdir()

    (api / "core.md").write_text('''---
title: Core
type: api
source_file: src/mylib/core.py
functions:
  - create_engine
  - nonexistent_function
---

# Core

The core module.

See also: [[utils]] and [[missing_page]]

```python
engine = create_engine()
result = engine.process(["hello"])
```
''')

    return docs
