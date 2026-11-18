"""날짜·시간 찾기와 형식 통일, 두 가지로 읽히는 날짜 판별."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .models import DateReading

WEEKDAYS_KO = "월화수목금토일"
WEEKDAYS_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# 연-월-일 (확실)
_YMD = re.compile(r"(?<!\d)(\d{4})\s*(?:년|[.\-/])\s*(\d{1,2})\s*(?:월|[.\-/])\s*(\d{1,2})(?:\s*일)?(?!\d)")
# 12월 3일 (확실)
_MD_KO = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# 12/03, 12-03 (두 가지로 읽힐 수 있음), 12.03 (한국식 월.일)
_SHORT = re.compile(r"(?<![\d./\-])(\d{1,2})\s*([./\-])\s*(\d{1,2})(?![\d]|\s*[./\-]\s*\d)")

_WEEKDAY_AFTER = re.compile(
    r"^\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*\)|([월화수목금토일])요일"
    r"|\(?\s*(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s*\)?)",
    re.IGNORECASE,
)

_TIME = re.compile(
    r"(오전|오후|AM|PM|am|pm)?\s*(?<!\d)(\d{1,2})\s*(?::\s*(\d{2})|시(?!간)\s*(?:(\d{1,2})\s*분|반)?)"
    r"\s*(AM|PM|am|pm)?"
)


def _weekday_after(text: str, pos: int) -> tuple[Optional[int], int]:
    m = _WEEKDAY_AFTER.match(text[pos:pos + 12])
    if not m:
        return None, pos
    ko = m.group(1) or m.group(2)
    if ko:
        return WEEKDAYS_KO.index(ko), pos + m.end()
    return WEEKDAYS_EN.index(m.group(3).lower()[:3]), pos + m.end()


def _valid(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _candidates(m: int, d: int, ref: date, weekday: Optional[int]) -> list[date]:
    """연도가 없는 월/일에 대해 기준일 근처의 날짜 후보를 고른다."""
    out = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        dt = _valid(y, m, d)
        if dt is None:
            continue
        delta = (dt - ref).days
        if -120 <= delta <= 300 and (weekday is None or dt.weekday() == weekday):
            out.append(dt)
    if not out and weekday is None:
        dt = _valid(ref.year, m, d)
        if dt:
            out.append(dt)
    return sorted(out, key=lambda x: abs((x - ref).days))


def find_dates(text: str, ref: Optional[date] = None, prefer: str = "MD") -> list[DateReading]:
    """줄에서 날짜를 모두 찾아 해석한다.

    prefer: 두 가지로 읽히고 요일로도 결정할 수 없을 때 기본으로 고르는 순서("MD"=월/일, "DM"=일/월).
    """
    ref = ref or date.today()
    found: list[DateReading] = []
    taken: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < e and s < b for s, e in taken)

    for m in _YMD.finditer(text):
        wd, end = _weekday_after(text, m.end())
        dt = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt is None:
            continue
        certain, reason = True, ""
        if wd is not None and dt.weekday() != wd:
            certain, reason = False, "요일이 날짜와 맞지 않음"
        found.append(DateReading(m.group(0), [dt], dt, certain, reason, wd, m.start(), end))
        taken.append((m.start(), end))

    for m in _MD_KO.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        wd, end = _weekday_after(text, m.end())
        cands = _candidates(int(m.group(1)), int(m.group(2)), ref, wd)
        if cands:
            found.append(DateReading(m.group(0), cands[:1], cands[0], True, "", wd, m.start(), end))
        else:
            loose = _candidates(int(m.group(1)), int(m.group(2)), ref, None)
            if loose:
                found.append(DateReading(m.group(0), loose[:1], loose[0], False,
                                         "요일이 날짜와 맞지 않음", wd, m.start(), end))
        taken.append((m.start(), end))

    for m in _SHORT.finditer(text):
        if overlaps(m.start(), m.end()):
            continue
        a, sep, b = int(m.group(1)), m.group(2), int(m.group(3))
        wd, end = _weekday_after(text, m.end())
        if sep == "." and wd is None and len(m.group(3)) < 2 and "~" not in text[m.end():m.end() + 3]:
            continue  # '4.5' 같은 소수와 헷갈리지 않도록 단서가 있을 때만 날짜로 본다
        md_ok = 1 <= a <= 12 and 1 <= b <= 31
        dm_ok = sep in "/-" and 1 <= b <= 12 and 1 <= a <= 31 and a != b
        ambiguous_format = md_ok and dm_ok
        interps = ([(a, b)] if md_ok else []) + ([(b, a)] if dm_ok else [])
        if not interps:
            continue
        options: list[date] = []
        for mm, dd in interps:
            c = _candidates(mm, dd, ref, wd)
            if c and c[0] not in options:
                options.append(c[0])
        if not options:
            loose = [c[0] for c in (_candidates(mm, dd, ref, None) for mm, dd in interps) if c]
            if loose:
                found.append(DateReading(m.group(0), loose, loose[0], False,
                                         "요일이 날짜와 맞지 않음", wd, m.start(), end))
                taken.append((m.start(), end))
            continue
        if len(options) == 1:
            reason = f"요일({WEEKDAYS_KO[wd]})로 판단" if ambiguous_format and wd is not None else ""
            found.append(DateReading(m.group(0), options, options[0], True, reason, wd, m.start(), end))
        else:
            if prefer == "DM":
                options.reverse()
            found.append(DateReading(m.group(0), options, options[0], False,
                                     "두 가지로 읽힐 수 있는 날짜", wd, m.start(), end))
        taken.append((m.start(), end))

    found.sort(key=lambda r: r.start)
    return found


def find_times(text: str) -> list[str]:
    """시간을 찾아 'HH:MM' 형식으로 통일한다."""
    out = []
    for m in _TIME.finditer(text):
        ampm = (m.group(1) or m.group(5) or "").lower()
        h = int(m.group(2))
        if m.group(3):
            mi = int(m.group(3))
        elif m.group(4):
            mi = int(m.group(4))
        elif "반" in m.group(0):
            mi = 30
        else:
            mi = 0
        if h > 24 or mi > 59:
            continue
        if ampm in ("오후", "pm") and h < 12:
            h += 12
        if ampm in ("오전", "am") and h == 12:
            h = 0
        out.append(f"{h:02d}:{mi:02d}")
    return out


def format_date(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일 {WEEKDAYS_KO[d.weekday()]}요일"


def format_time(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    part = "오전" if h < 12 else "오후"
    h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{part} {h12}시" + (f" {m}분" if m else "")


def iso(d: date) -> str:
    return d.isoformat()


def days_until(d: date, ref: Optional[date] = None) -> int:
    return (d - (ref or date.today())).days

