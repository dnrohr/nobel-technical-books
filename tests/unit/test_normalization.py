from nobel_books.normalization.dates import parse_date
from nobel_books.normalization.identifiers import (
    is_valid_isbn10,
    is_valid_isbn13,
    isbn10_to_isbn13,
)
from nobel_books.normalization.languages import normalize_language
from nobel_books.normalization.roles import normalize_role
from nobel_books.normalization.titles import normalize_title


def test_normalization_primitives() -> None:
    assert normalize_title("  Quantum—Mechanics: Vol. II  ") == "quantum mechanics vol ii"
    assert normalize_title("E = mc²") == "e = mc2"
    assert is_valid_isbn10("0-306-40615-2")
    assert isbn10_to_isbn13("0-306-40615-2") == "9780306406157"
    assert is_valid_isbn13("978-0-306-40615-7")
    assert not is_valid_isbn13("978-0-306-40615-8")
    date_range = "circa 1910\u20131912"
    assert parse_date(date_range).lower_year == 1910
    assert parse_date(date_range).upper_year == 1912
    assert parse_date(date_range).uncertain
    assert normalize_language("/languages/eng") == "en"
    assert normalize_role(None) == "unknown"
    assert normalize_role(None, field_guarantees_authorship=True) == "author"
    assert normalize_role("Edited by") == "unknown"
