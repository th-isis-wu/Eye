"""⑤ 정보 추출: 행사명, 일시, 장소, 신청 방법, 마감을 찾고 날짜·시간 형식을 통일한다."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from . import dates as D
from .models import Document, InfoField, Line

FIELD_NAMES = {
    "title": "행사명",
    "datetime": "일시",
    "place": "장소",
    "apply": "신청 방법",
    "deadline": "마감",
}

_BULLET = r"^\s*[■□▶▷►●○◆◇•·\-*※☞✔✓★☆◎▣\[]?\s*"
# 순서가 중요하다: '신청 기간'은 신청 방법이 아니라 마감으로 본다.
LABELS: list[tuple[str, str]] = [
    ("deadline", r"(?:신청|접수|모집|지원)\s*(?:기간|기한|마감)|마감(?:일|\s*일시)?|기한|deadline"),
    ("datetime", r"(?:행사\s*)?(?:일\s*시|일\s*정|날\s*짜|시\s*간|기\s*간)|행사\s*일|when|date"),
    ("place", r"(?:행사\s*)?(?:장\s*소|위\s*치)|where|place|location"),
    ("title", r"행사\s*명|제\s*목|프로그램\s*명|주\s*제|강연\s*명|title"),
    ("apply", r"(?:신청|접수|참여|참가|지원)\s*(?:방법|방식|링크|처)?|apply"),
]
_LABEL_RE = [(name, re.compile(_BULLET + r"(?:" + pat + r")\s*(?:\]\s*)?(?:[:：|]\s*|\s+|$)(.*)$", re.IGNORECASE))
             for name, pat in LABELS]

URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|kr|net|org|ly|gl|me|io)(?:/\S*)?\b|forms\.gle/\S+|bit\.ly/\S+",
                 re.IGNORECASE)
PLACE_HINT = re.compile(
    r"[가-힣A-Za-z0-9]+(?:관|홀|센터|강당|강의실|회의실|세미나실|대강당|학생회관|도서관|캠퍼스|광장|라운지|\d+호|\d+층)"
    r"|온라인|비대면|zoom|줌|유튜브|youtube|webex|웹엑스|teams",
    re.IGNORECASE,
)
APPLY_HINT = re.compile(r"구글\s*폼|google\s*form|QR|큐알|링크|신청|접수|카카오\s*채널|오픈\s*채팅|이메일|e-?mail|@", re.IGNORECASE)
DEADLINE_HINT = re.compile(r"마감|까지|기한|~\s*$")


def _match_label(text: str) -> Optional[tuple[str, str]]:
    for name, rx in _LABEL_RE:
        m = rx.match(text)
        if m:
            return name, m.group(1).strip()
    return None


def describe(text: str, readings: list[D.DateReading]) -> str:
    """줄 안의 날짜·시간을 '2026년 12월 3일 목요일 오후 2시' 꼴로 통일한다."""
    times = D.find_times(text)
    is_range = bool(re.search(r"[~\-–]|부터", text))
    parts = []
    for r in readings:
        if r.chosen:
            parts.append(D.format_date(r.chosen) + ("" if r.certain else " (확실하지 않음)"))
    if len(parts) >= 2 and is_range:
        parts[0] += "부터"
        parts[1] += "까지"
    if times:
        if len(times) >= 2 and is_range:
            parts.append(f"{D.format_time(times[0])}부터 {D.format_time(times[1])}까지")
        else:
            parts.append(", ".join(D.format_time(t) for t in times))
    return " ".join(parts)


def _describe_dates(text: str, ref: date, prefer: str) -> tuple[str, list[D.DateReading]]:
    readings = D.find_dates(text, ref, prefer)
    return describe(text, readings), readings


def extract(doc: Document, ref: Optional[date] = None, prefer: str = "MD") -> dict[str, InfoField]:
    ref = ref or date.today()
    lines: list[Line] = doc.lines
    texts = [l.text.strip() for l in lines]
    fields: dict[str, InfoField] = {}

    def put(name: str, raw: str, *, with_dates: bool = False, src: tuple[int, ...] = ()) -> None:
        if name in fields or not raw:
            return
        value, readings = (raw, [])
        if with_dates:
            desc, readings = _describe_dates(raw, ref, prefer)
            if desc:
                value = desc
        if name == "apply":
            urls = URL.findall(raw)
            if urls:
                value = raw
        words = [w for i in src for w in lines[i].words]
        fields[name] = InfoField(name, value, raw, any(not r.certain for r in readings), readings, words)

    # 1) '일시:', '장소 :' 처럼 이름표가 붙은 줄
    for i, text in enumerate(texts):
        hit = _match_label(text)
        if not hit:
            continue
        name, val = hit
        src: tuple[int, ...] = (i,)
        if not val and i + 1 < len(texts) and not _match_label(texts[i + 1]):
            val, src = texts[i + 1], (i, i + 1)
        if not val:
            continue
        put(name, val, with_dates=name in ("datetime", "deadline"), src=src)

    # 2) 이름표가 없을 때: 줄 내용으로 추측
    used_for_deadline: set[int] = set()
    if "deadline" not in fields:
        for i, text in enumerate(texts):
            if DEADLINE_HINT.search(text) and D.find_dates(text, ref, prefer):
                put("deadline", text, with_dates=True, src=(i,))
                used_for_deadline.add(i)
                break
    if "datetime" not in fields:
        for i, text in enumerate(texts):
            if i in used_for_deadline or _match_label(text):
                continue
            if D.find_dates(text, ref, prefer):
                put("datetime", text, with_dates=True, src=(i,))
                break
    if "place" not in fields:
        for i, text in enumerate(texts):
            if _match_label(text):
                continue
            m = PLACE_HINT.search(text)
            if m and not D.find_dates(text, ref, prefer):
                put("place", text, src=(i,))
                break
    if "apply" not in fields:
        for i, text in enumerate(texts):
            if URL.search(text):
                put("apply", text, src=(i,))
                break
        else:
            for i, text in enumerate(texts):
                if APPLY_HINT.search(text) and not _match_label(text):
                    put("apply", text, src=(i,))
                    break

    # 3) 행사명: 이름표가 없으면 위쪽에서 가장 큰 글자 줄(제목)을 쓴다
    if "title" not in fields and lines:
        title_lines = guess_title(doc, ref, prefer)
        if title_lines:
            idx = tuple(i for i, l in enumerate(lines) if any(l is t for t in title_lines))
            put("title", " ".join(t.text.strip() for t in title_lines), src=idx)
    return fields


def guess_title(doc: Document, ref: date, prefer: str) -> list[Line]:
    cands = []
    for b in doc.blocks:
        for l in b.lines:
            t = l.text.strip()
            if len(t.replace(" ", "")) < 2 or _match_label(t) or D.find_dates(t, ref, prefer) or URL.search(t):
                continue
            if not re.search(r"[가-힣A-Za-z]", t):
                continue
            cands.append(l)
    if not cands:
        return []
    top = max(cands, key=lambda l: (round(l.height / 4), -l.y))
    # 같은 크기로 바로 이어지는 줄은 제목 두 줄로 본다
    parts = [top]
    for l in cands:
        if l is top:
            continue
        if abs(l.height - top.height) <= 0.2 * top.height and 0 <= l.y - parts[-1].bottom <= 0.8 * top.height \
                and min(l.right, top.right) > max(l.x, top.x):
            parts.append(l)
    return parts
