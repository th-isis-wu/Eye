"""파이프라인 전체에서 쓰는 데이터 구조."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional


@dataclass
class Word:
    """OCR(또는 PDF 글자 정보)로 얻은 글자 한 덩어리: 내용 + 위치(좌표) + 확신도."""

    text: str
    x: float
    y: float
    w: float
    h: float
    conf: float = 100.0  # 0~100
    page: int = 0
    ocr: bool = True  # False면 PDF에 원래 들어 있던 글자 (띄어쓰기가 정확함)

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


_HANGUL = re.compile(r"[가-힣]")
_JOINABLE = re.compile(r"^[가-힣0-9()\[\]]{1,4}$")


def _join_tight(a: Word, b: Word, line_h: float) -> bool:
    """한글 OCR은 글자 하나씩 끊어 읽는 일이 많다. 간격이 좁으면 붙여 쓴다."""
    if not (a.ocr and b.ocr) or b.x - a.right >= 0.3 * line_h:
        return False
    if a.text.endswith(("(", "[")) or b.text.startswith((")", "]", ",", ".")):
        return True
    return bool(_JOINABLE.match(a.text) and _JOINABLE.match(b.text)
                and (_HANGUL.search(a.text) or _HANGUL.search(b.text)))


@dataclass
class Line:
    words: list[Word]

    @property
    def text(self) -> str:
        return self.render()

    def render(self, fmt: Optional[Callable[[Word], str]] = None) -> str:
        """줄의 글. fmt를 주면 단어마다 모양을 바꿀 수 있다 (예: 불확실한 글자 표시)."""
        if not self.words:
            return ""
        fmt = fmt or (lambda w: w.text)
        line_h = max(w.h for w in self.words)
        out = fmt(self.words[0])
        for a, b in zip(self.words, self.words[1:]):
            out += ("" if _join_tight(a, b, line_h) else " ") + fmt(b)
        return out

    @property
    def x(self) -> float:
        return min(w.x for w in self.words)

    @property
    def y(self) -> float:
        return min(w.y for w in self.words)

    @property
    def right(self) -> float:
        return max(w.right for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def height(self) -> float:
        hs = sorted(w.h for w in self.words)
        return hs[len(hs) // 2]

    @property
    def conf(self) -> float:
        return min(w.conf for w in self.words)


@dataclass
class Block:
    """가까운 글자 줄을 묶은 덩어리. kind: heading / paragraph / list / table."""

    lines: list[Line]
    kind: str = "paragraph"
    rows: list[list[str]] = field(default_factory=list)  # kind == "table"일 때 칸

    @property
    def x(self) -> float:
        return min(l.x for l in self.lines)

    @property
    def y(self) -> float:
        return min(l.y for l in self.lines)

    @property
    def right(self) -> float:
        return max(l.right for l in self.lines)

    @property
    def bottom(self) -> float:
        return max(l.bottom for l in self.lines)

    @property
    def height(self) -> float:
        hs = sorted(l.height for l in self.lines)
        return hs[len(hs) // 2]

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    @property
    def words(self) -> list[Word]:
        return [w for l in self.lines for w in l.words]


@dataclass
class Page:
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Document:
    source: str
    kind: str = "image"  # image / pdf
    pages: list[Page] = field(default_factory=list)
    is_scanned: bool = False
    source_url: Optional[str] = None

    @property
    def blocks(self) -> list[Block]:
        return [b for p in self.pages for b in p.blocks]

    @property
    def lines(self) -> list[Line]:
        return [l for b in self.blocks for l in b.lines]

    @property
    def words(self) -> list[Word]:
        return [w for l in self.lines for w in l.words]


@dataclass
class DateReading:
    """날짜 표기를 해석한 결과. 두 가지로 읽히면 options가 2개 이상."""

    raw: str
    options: list[date]
    chosen: Optional[date]
    certain: bool
    reason: str = ""
    weekday_hint: Optional[int] = None  # 0=월 ... 6=일
    start: int = 0  # 줄 안에서의 위치
    end: int = 0


@dataclass
class Uncertainty:
    kind: str  # "low_conf" / "ambiguous_date"
    text: str
    message: str
    options: list[str] = field(default_factory=list)
    chosen: Optional[str] = None
    field_name: Optional[str] = None
    word: Optional[Word] = None
    reading: Optional[DateReading] = None
    resolved: bool = False


@dataclass
class InfoField:
    name: str  # title / datetime / place / apply / deadline
    value: str
    raw: str = ""
    uncertain: bool = False
    dates: list[DateReading] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)  # 이 정보를 읽어 온 글자들


@dataclass
class Result:
    document: Document
    fields: dict[str, InfoField] = field(default_factory=dict)
    uncertainties: list[Uncertainty] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)  # 사용자에게 알릴 말 (예: 스캔본)
