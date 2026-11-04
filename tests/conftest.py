"""Gemeinsame pytest-Fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from atn_dq.config import load_config  # noqa: E402
from atn_dq.loader import load_package  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config(ROOT / "config")


@pytest.fixture(scope="session")
def pkg():
    return load_package(ROOT / "data" / "input")
