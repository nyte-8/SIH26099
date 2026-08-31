# units.py
#
# Unit normalization (item 4): convert whatever unit a value arrives in
# to the canonical SI-ish unit each attribute is compared in, so "2 inch"
# and "50mm" land on the same number before the tolerance check runs.
#
# Each table maps every recognized unit spelling to a multiplier that
# converts INTO the canonical unit (the entry equal to 1.0).

_UNIT_TABLES = {
    "mm": {"mm": 1, "millimeter": 1, "millimetre": 1, "cm": 10, "centimeter": 10,
           "m": 1000, "meter": 1000, "metre": 1000,
           "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4,
           "ft": 304.8, "feet": 304.8},
    "m": {"m": 1, "meter": 1, "metre": 1, "mm": 0.001, "cm": 0.01,
          "ft": 0.3048, "feet": 0.3048},
    "bar": {"bar": 1, "psi": 0.0689476, "kpa": 0.01, "mpa": 10, "pa": 0.00001},
    "kv": {"kv": 1, "v": 0.001, "volt": 0.001, "volts": 0.001},
    "v": {"v": 1, "volt": 1, "volts": 1, "kv": 1000},
    "kw": {"kw": 1, "w": 0.001, "watt": 0.001, "watts": 0.001, "hp": 0.7457},
    "sqmm": {"sqmm": 1, "mm2": 1, "sq mm": 1, "sqcm": 100, "cm2": 100},
    "a": {"a": 1, "amp": 1, "amps": 1, "ampere": 1, "amperes": 1},
    "m3h": {"m3h": 1, "m3/h": 1, "lpm": 0.06, "lps": 3.6},
    "pct": {"pct": 1, "%": 1, "percent": 1},
    "rpm": {"rpm": 1},
    "count": {"count": 1, "": 1},
}


def normalize(value: float, from_unit: str, canonical_unit: str) -> float:
    """Converts `value` (given in `from_unit`) into `canonical_unit`.
    Falls back to returning the raw value unchanged if the unit isn't
    recognized -- better to compare a possibly-wrong-unit number than to
    drop the attribute entirely."""
    table = _UNIT_TABLES.get(canonical_unit)
    if not table:
        return value
    key = (from_unit or canonical_unit).strip().lower()
    factor = table.get(key)
    if factor is None:
        return value
    return round(value * factor, 4)


def parse_quantity(text: str):
    """Pulls the first `<number><unit>` pair out of free text, e.g.
    '50mm' -> (50.0, 'mm'), '2 inch' -> (2.0, 'inch'). Returns None if no
    number is found. This is a best-effort fallback for when there's no
    LLM available to do proper extraction."""
    import re
    if not text:
        return None
    match = re.search(r'(-?\d+(?:\.\d+)?)\s*([a-zA-Z"%]*)', text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    return value, unit


def unit_is_recognized(from_unit: str, canonical_unit: str) -> bool:
    """True if `from_unit` is an explicit, known spelling for `canonical_unit`
    (e.g. 'cm' or 'inch' for canonical 'mm'). False for an empty/unknown unit
    -- used to tell a confident unit match apart from a bare, unitless number
    that just happens to be sitting in the text."""
    table = _UNIT_TABLES.get(canonical_unit)
    if not table:
        return False
    key = (from_unit or "").strip().lower()
    return bool(key) and key in table


def parse_quantities(text: str):
    """Return every number/unit pair in a description in source order."""
    import re
    if not text:
        return []
    return [
        (float(value), unit.lower())
        for value, unit in re.findall(r'(-?\d+(?:\.\d+)?)\s*([a-zA-Z"%]*)', text)
    ]
