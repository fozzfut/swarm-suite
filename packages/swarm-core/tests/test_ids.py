"""Tests for swarm_core.ids."""

import re

import pytest

from swarm_core.ids import generate_id


def test_generate_id_default_format():
    out = generate_id("f")
    assert re.match(r"^f-[0-9a-f]{4}$", out)


def test_generate_id_custom_length():
    out = generate_id("fp", length=6)
    assert re.match(r"^fp-[0-9a-f]{12}$", out)


def test_generate_id_uniqueness():
    ids = {generate_id("x") for _ in range(1000)}
    # 16-bit suffix gives ~256 collision threshold; 1000 generations may
    # hit one or two -- just check we got mostly distinct values.
    assert len(ids) > 950


def test_generate_id_rejects_empty_prefix():
    with pytest.raises(ValueError):
        generate_id("")


def test_generate_id_rejects_uppercase():
    with pytest.raises(ValueError):
        generate_id("FX")


def test_generate_id_rejects_invalid_length():
    with pytest.raises(ValueError):
        generate_id("f", length=0)
