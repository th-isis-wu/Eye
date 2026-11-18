"""⑥ 검증: 확신도가 낮은 글자와 두 가지로 읽히는 날짜·숫자를 찾아 '확실하지 않음'으로 표시한다."""
from __future__ import annotations

import re

from . import dates as D
from .extract import FIELD_NAMES, describe
from .models import InfoField, Result, Uncertainty

# OCR이 자주 헷갈리는 글자 (숫자 안에 섞이면 두 가지로 읽힌다)
CONFUSABLE = re.compile(r"\d[OoIl|SsBZ]|[OoIl|SsBZ]\d")


def verify(result: Result, threshold: float = 60.0) -> list[Uncertainty]:
    out: list[Uncertainty] = []
    owner = {id(w): name for name, f in result.fields.items() for w in f.words}

    # 1) 두 가지로 읽히거나 요일과 맞지 않는 날짜
    for name, f in result.fields.items():
        for r in f.dates:
            if r.certain:
                continue
            opts = [D.format_date(d) for d in r.options]
            out.append(Uncertainty(
                kind="ambiguous_date",
                text=r.raw,
                message=f"{FIELD_NAMES[name]}의 '{r.raw}': {r.reason}",
                options=opts,
                chosen=D.format_date(r.chosen) if r.chosen else None,
                field_name=name,
                reading=r,
            ))

    # 2) 확신도가 낮은 글자, 숫자와 헷갈리는 글자
    seen: set[int] = set()
    for w in result.document.words:
        low = w.conf < threshold
        confusable = bool(CONFUSABLE.search(w.text)) and w.conf < 90
        if not (low or confusable) or id(w) in seen:
            continue
        seen.add(id(w))
        why = f"확신도 {w.conf:.0f}%" if low else "숫자와 비슷한 글자가 섞여 있음"
        out.append(Uncertainty(
            kind="low_conf",
            text=w.text,
            message=f"'{w.text}' 글자가 확실하지 않습니다 ({why}).",
            field_name=owner.get(id(w)),
            word=w,
        ))

    for u in out:
        if u.field_name and u.field_name in result.fields:
            result.fields[u.field_name].uncertain = True
    return out


def apply_date_choice(f: InfoField, index: int, choice: int) -> None:
    """사용자가 고른 날짜를 필드에 반영한다."""
    r = f.dates[index]
    r.chosen = r.options[choice]
    r.certain = True
    r.reason = "사용자가 선택"
    f.uncertain = any(not x.certain for x in f.dates)
    f.value = describe(f.raw, f.dates) or f.value
