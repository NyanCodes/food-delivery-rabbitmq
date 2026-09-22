import pytest
from pydantic import ValidationError

from app.models import OrderIn


def valid_order(**overrides):
    data = {
        "customer": "Aung",
        "restaurant": "Shan Noodle House",
        "items": ["Shan noodles"],
        "total": 180.0,
    }
    data.update(overrides)
    return OrderIn(**data)


def test_valid_order():
    assert valid_order().total == 180.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("customer", ""),
        ("restaurant", ""),
        ("items", []),
        ("total", 0),
        ("total", -1),
        ("total", 100_001),
    ],
)
def test_invalid_order(field, value):
    with pytest.raises(ValidationError):
        valid_order(**{field: value})
