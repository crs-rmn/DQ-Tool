"""Normalisierungs-Helpers für die geladenen Rohdaten.

Diese Funktionen verändern die Originaldaten nicht destruktiv - sie liefern
Vergleichs- und Prüfhilfen (Trim, Upper, Preisnormalisierung, Ländernamen,
Datumsparsing). So bleiben die Originalwerte für Reports erhalten.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


ISO3166_ALIAS = {
    "DE": "Germany", "NL": "Netherlands", "BE": "Belgium", "FR": "France",
    "ES": "Spain", "IT": "Italy", "AT": "Austria", "CH": "Switzerland",
    "PL": "Poland", "CZ": "Czechia", "DK": "Denmark", "SE": "Sweden",
    "NO": "Norway", "FI": "Finland", "UK": "United Kingdom",
    "GB": "United Kingdom", "US": "United States", "USA": "United States",
    "BR": "Brazil", "CA": "Canada", "AR": "Argentina", "AU": "Australia",
    "CN": "China", "IN": "India",
}

COUNTRY_TO_REGION = {
    "Germany": "DACH", "Austria": "DACH", "Switzerland": "DACH",
    "Netherlands": "Benelux", "Belgium": "Benelux", "Luxembourg": "Benelux",
    "France": "Westeuropa", "Spain": "Westeuropa", "Italy": "Westeuropa",
    "Portugal": "Westeuropa", "Ireland": "Westeuropa",
    "United Kingdom": "Westeuropa",
    "Poland": "Osteuropa", "Czechia": "Osteuropa", "Hungary": "Osteuropa",
    "Romania": "Osteuropa", "Slovakia": "Osteuropa", "Bulgaria": "Osteuropa",
    "Croatia": "Osteuropa", "Slovenia": "Osteuropa",
    "Denmark": "Nordeuropa", "Sweden": "Nordeuropa",
    "Norway": "Nordeuropa", "Finland": "Nordeuropa",
    "Brazil": "Suedamerika", "Argentina": "Suedamerika",
    "Chile": "Suedamerika", "Peru": "Suedamerika",
    "United States": "Nordamerika", "Canada": "Nordamerika",
    "Mexico": "Nordamerika",
    "China": "Asien", "India": "Asien", "Japan": "Asien",
    "Australia": "Ozeanien", "New Zealand": "Ozeanien",
}


def is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float):
        try:
            import math
            if math.isnan(v):
                return True
        except Exception:
            pass
    s = str(v).strip()
    return s == "" or s.lower() in ("nan", "none", "null", "-", "n/a", "na")


def strip_str(v: Any) -> str | None:
    if is_missing(v):
        return None
    return str(v).strip()


def norm_upper(v: Any) -> str | None:
    s = strip_str(v)
    return s.upper() if s else None


def norm_name(v: Any) -> str | None:
    """Vereinheitlicht einen Produkt-/Firmennamen für Vergleichszwecke."""
    s = strip_str(v)
    if not s:
        return None
    # mehrfache Leerzeichen zusammenfassen
    s = " ".join(s.split())
    return s.lower()


def norm_country(v: Any) -> str | None:
    s = strip_str(v)
    if not s:
        return None
    up = s.upper()
    if up in ISO3166_ALIAS:
        return ISO3166_ALIAS[up]
    # Titlecase
    return s.title() if s.islower() or s.isupper() else s


def country_to_region(country: str | None) -> str:
    if not country:
        return "Nicht zugeordnet"
    canonical = norm_country(country) or country
    return COUNTRY_TO_REGION.get(canonical, "Nicht zugeordnet")


def norm_price(v: Any) -> float | None:
    if is_missing(v):
        return None
    try:
        s = str(v).strip().replace(" ", "")
        # Deutsche Notation "1.234,56" -> "1234.56"
        if "," in s and "." in s and s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


def norm_currency(v: Any) -> str | None:
    s = norm_upper(v)
    if not s:
        return None
    # "EURO" -> "EUR"
    if s == "EURO":
        return "EUR"
    return s


def norm_matnr(v: Any) -> str | None:
    """Materialnummer - führende Nullen behalten, Leerzeichen entfernen.

    Pandas liest numerische MATNRs manchmal als Float (1000000001.0). Wir
    schneiden ein trailing '.0' ab, bewahren aber führende Nullen.
    """
    s = strip_str(v)
    if not s:
        return None
    if s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        s = s[:-2]
    return s


def parse_date(v: Any) -> datetime | None:
    if is_missing(v):
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except Exception:
        return None


def normalize_bool(v: Any) -> bool | None:
    s = strip_str(v)
    if not s:
        return None
    up = s.upper()
    if up in ("TRUE", "WAHR", "YES", "JA", "1", "X"):
        return True
    if up in ("FALSE", "FALSCH", "NO", "NEIN", "0"):
        return False
    return None
