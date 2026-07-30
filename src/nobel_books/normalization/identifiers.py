"""ISBN normalization, validation, and conversion."""

import re

SEPARATORS = re.compile(r"[\s-]+")


def normalize_isbn(value: str) -> str:
    return SEPARATORS.sub("", value).upper()


def is_valid_isbn10(value: str) -> bool:
    value = normalize_isbn(value)
    if not re.fullmatch(r"\d{9}[\dX]", value):
        return False
    total = sum(
        (10 - index) * (10 if digit == "X" else int(digit)) for index, digit in enumerate(value)
    )
    return total % 11 == 0


def is_valid_isbn13(value: str) -> bool:
    value = normalize_isbn(value)
    if not re.fullmatch(r"\d{13}", value):
        return False
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(value[:12]))
    return (10 - total % 10) % 10 == int(value[-1])


def isbn10_to_isbn13(value: str) -> str | None:
    value = normalize_isbn(value)
    if not is_valid_isbn10(value):
        return None
    stem = f"978{value[:9]}"
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(stem))
    return f"{stem}{(10 - total % 10) % 10}"
