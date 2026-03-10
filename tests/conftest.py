"""Shared pytest fixtures for the netforge test suite."""
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def hp_config() -> str:
    return (FIXTURES / "hp_sample.txt").read_text()


@pytest.fixture
def allied_config() -> str:
    return (FIXTURES / "allied_sample.txt").read_text()
