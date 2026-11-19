"""Small date-range parser shared by the normal and demo shooting plans."""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _dates_in(text: str) -> list[date]:
    text = text or ""
    found: list[date] = []
    # ISO: 2026-11-24, 2026/11/24, 2026.11.24
    for y, m, d in re.findall(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?", text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    # Chinese month/day, without a year: 11月24日
    if not found:
        for m, d in re.findall(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text):
            try:
                today = date.today()
                candidate = date(today.year, int(m), int(d))
                if candidate < today - timedelta(days=30):
                    candidate = date(today.year + 1, int(m), int(d))
                found.append(candidate)
            except ValueError:
                pass
    # English: 24 Nov 2026 / Nov 24 2026 / 24 November
    if not found:
        pattern = r"(?<!\d)(\d{1,2})\s+([A-Za-z]{3,9})(?:\s+(20\d{2}))?"
        for d, mon, y in re.findall(pattern, text):
            month = MONTHS.get(mon.lower())
            if not month:
                continue
            try:
                year = int(y) if y else date.today().year
                candidate = date(year, month, int(d))
                if not y and candidate < date.today() - timedelta(days=30):
                    candidate = date(year + 1, month, int(d))
                found.append(candidate)
            except ValueError:
                pass
    # de-duplicate while preserving order
    out = []
    for item in found:
        if item not in out:
            out.append(item)
    return out


def parse_range(text: str) -> tuple[date | None, date | None]:
    """Return (start, end) from natural language; either may be None."""
    text = text or ""
    dates = _dates_in(text)
    if not dates:
        return None, None
    start = dates[0]
    end = dates[1] if len(dates) > 1 else None
    if end and end < start:
        start, end = end, start
    return start, end


def range_days(start: date | None, end: date | None) -> int | None:
    if start and end:
        return max(1, (end - start).days + 1)
    return None


def date_sequence(start: date | None, count: int) -> list[str]:
    if not start:
        return []
    return [(start + timedelta(days=i)).isoformat() for i in range(max(0, count))]


_WORD_DAYS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_CN_DAYS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15}


def parse_day_count(text: str) -> int | None:
    """Read an explicit shooting-day count such as '8 days' / '八天'."""
    value = text or ""
    m = re.search(r"(\d{1,2})\s*(?:days?|天)", value, re.I)
    if m:
        number = int(m.group(1))
        if 1 <= number <= 30:
            return number
    m = re.search(r"\b(" + "|".join(_WORD_DAYS) + r")\s+days?\b", value, re.I)
    if m:
        return _WORD_DAYS[m.group(1).lower()]
    m = re.search(r"([一二三四五六七八九十]{1,2})\s*天", value)
    if m and m.group(1) in _CN_DAYS:
        return _CN_DAYS[m.group(1)]
    return None
