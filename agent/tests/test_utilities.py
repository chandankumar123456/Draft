"""Unit tests for the utility tools in tools/functions.py."""

import json
import uuid
from datetime import datetime

import pytest

from tools.functions import calculate, generate_uuid, get_current_time


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("sqrt(16)", 4.0),
        ("2 ** 10", 1024),
        ("7 // 2", 3),
    ],
)
def test_calculate_valid(expression, expected):
    result = calculate(expression)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["result"] == expected
    assert result["data"]["expression"] == expression
    assert result["data"]["result_type"] in ("int", "float")


def test_calculate_pi():
    result = calculate("pi")
    assert_envelope(result)
    assert result["success"]
    assert abs(result["data"]["result"] - 3.14159) < 0.001


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "lambda: 1",
        "[1,2,3]",
        "a = 1",
        "open('x')",
        "1 if True else 2",
        "math.sqrt(4)",
        "",
        "1/0",
    ],
)
def test_calculate_rejected(expression):
    result = calculate(expression)
    assert_envelope(result)
    assert not result["success"]


def test_generate_uuid():
    result = generate_uuid()
    assert_envelope(result)
    assert result["success"]
    uuid.UUID(result["data"]["uuid"])


def test_get_current_time():
    result = get_current_time()
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    datetime.fromisoformat(data["iso"])
    assert isinstance(data["timestamp"], float)
    assert data["utc"] is False


def test_get_current_time_utc():
    result = get_current_time(utc=True)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["utc"] is True
    datetime.fromisoformat(result["data"]["iso"])
