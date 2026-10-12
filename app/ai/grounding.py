"""Check that every number in an AI answer appears in the facts it was given.

This catches the model inventing or recalculating a metric. It doesn't prove the answer is
right, but an answer that passes uses only numbers the database produced.
"""

import re
from datetime import date, datetime

NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")

# Small whole numbers are usually list markers, counts written in prose ("two of three"),
# or ordinals, and years appear in dates; neither is a metric the model could invent.
SMALL_NUMBER_LIMIT = 10


def _variants(value: float) -> set[str]:
    """Ways a number from the facts may legitimately be written in the answer."""
    forms = set()
    for number in (value, value * 100):  # rates may be shown as fractions or percentages
        for digits in (0, 1, 2):
            rounded = round(number, digits)
            forms.add(f"{rounded:.{digits}f}")
            if rounded == int(rounded):
                forms.add(str(int(rounded)))
    return forms


def _collect(value, out: set[str]):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out |= _variants(float(value))
    elif isinstance(value, str):
        for match in NUMBER.findall(value):
            out |= _variants(float(match.replace(",", "")))
    elif isinstance(value, (date, datetime)):
        _collect(value.isoformat(), out)
    elif isinstance(value, dict):
        for item in value.values():
            _collect(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, out)


def ungrounded_numbers(answer: str, facts, question: str | None = None) -> list[str]:
    allowed: set[str] = set()
    _collect(facts, allowed)
    if question:
        _collect(question, allowed)

    unknown = []
    for match in NUMBER.findall(answer):
        text = match.replace(",", "")
        number = float(text)
        if number.is_integer() and (abs(number) <= SMALL_NUMBER_LIMIT or 1900 <= number <= 2100):
            continue
        normalised = text.rstrip("0").rstrip(".") if "." in text else text
        if text not in allowed and normalised not in allowed:
            unknown.append(match)
    return sorted(set(unknown))
