"""Tests for example module."""

from src.example import greet


def test_greet():
    """Test greet function."""
    assert greet("Alice") == "Hello, Alice!"
    assert greet("Bob") == "Hello, Bob!"
