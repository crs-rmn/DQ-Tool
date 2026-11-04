"""Tests für Normalisierungs-Helfer."""
from __future__ import annotations

from atn_dq.normalize import (
    country_to_region,
    is_missing,
    norm_country,
    norm_currency,
    norm_matnr,
    norm_price,
    parse_date,
)


def test_is_missing():
    for v in (None, "", "   ", "nan", "NaN", "n/a", "-"):
        assert is_missing(v)
    for v in ("foo", 0, "0", "False"):
        assert not is_missing(v)


def test_norm_matnr_keeps_leading_zero_and_strips_float():
    assert norm_matnr("1000000001") == "1000000001"
    assert norm_matnr("1000000001.0") == "1000000001"
    assert norm_matnr(" 00042 ") == "00042"
    assert norm_matnr(None) is None


def test_norm_currency():
    assert norm_currency("EURO") == "EUR"
    assert norm_currency(" eur ") == "EUR"


def test_norm_country_and_region():
    assert norm_country("NL") == "Netherlands"
    assert norm_country("de") == "Germany"          # ISO-Alias
    assert norm_country("foo-land") == "foo-land".title()  # unbekannt -> Titelcase
    assert country_to_region("Germany") == "DACH"
    assert country_to_region("BR") == "Suedamerika"
    assert country_to_region(None) == "Nicht zugeordnet"


def test_norm_price():
    assert norm_price("1.234,56") == 1234.56
    assert norm_price("100") == 100.0
    assert norm_price("  nan ") is None
    assert norm_price(None) is None


def test_parse_date():
    assert parse_date("2024-05-03").year == 2024
    assert parse_date("20240101").month == 1
    assert parse_date("30.12.2025").day == 30
    assert parse_date("nicht ein datum") is None
