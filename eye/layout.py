"""④ 읽는 순서: 가까운 글자를 블록으로 묶고 위→아래, 왼→오른쪽으로 정렬한다.
여러 단과 표는 칸 단위로 나눠 읽는다. PDF는 제목·문단·번호 목록·표를 구분하고 쪽 번호·머리말을 뺀다."""
from __future__ import annotations

import re
from statistics import median

from .models import Block, Line, Page, Word

LIST_MARK = re.compile(r"^\s*(?:[-•·▪▶▷●○◆◇■□※☞✔✓*]|\d{1,2}[.)]|[①-⑳]|[가-하][.)]|\(\d{1,2}\))\s*")
PAGE_NO = re.compile(r"^\s*(?:[-–—]\s*)?(?:p\.?\s*)?\d{1,4}(?:\s*[/of]+\s*\d{1,4})?(?:\s*[-–—])?\s*$|^\s*\d{1,4}\s*쪽\s*$",
                     re.IGNORECASE)


# ---------------------------------------------------------------- 줄 만들기
def _v_overlap(a: Word | Line, b: Word | Line) -> float:
    top, bot = max(a.y, b.y), min(a.bottom, b.bottom)
    h = min(a.bottom - a.y, b.bottom - b.y) or 1
    return max(0.0, bot - top) / h


def group_lines(words: list[Word], gap_factor: float = 2.0) -> list[Line]:
    """세로로 겹치는 단어를 한 줄로 묶고, 가로 간격이 크면 다른 칸(단)으로 나눈다."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x)):
        for row in rows:
            ref = Line(row)
            if _v_overlap(w, ref) >= 0.5 and 0.4 <= w.h / (ref.height or 1) <= 2.5:
                row.append(w)
                break
        else:
            rows.append([w])

    lines: list[Line] = []
    for row in rows:
        row.sort(key=lambda w: w.x)
        h = median(w.h for w in row) or 1
        cur = [row[0]]
        for w in row[1:]:
            if w.x - cur[-1].right > gap_factor * h:
                lines.append(Line(cur))
                cur = [w]
            else:
                cur.append(w)
        lines.append(Line(cur))
    return lines


# ---------------------------------------------------------------- 표 찾기
def _rows_of(lines: list[Line]) -> list[list[Line]]:
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda l: (l.y + l.bottom) / 2):
        for row in rows:
            if _v_overlap(ln, row[0]) >= 0.5:
                row.append(ln)
                break
        else:
            rows.append([ln])
    for r in rows:
        r.sort(key=lambda l: l.x)
    return rows


def find_tables(lines: list[Line]) -> tuple[list[Block], list[Line]]:
    """세 칸 이상이 같은 위치에 나란히 반복되는 줄 묶음을 표로 본다. (표 블록, 남은 줄)."""
    rows = _rows_of(lines)
    tables: list[Block] = []
    used: set[int] = set()
    i = 0
    while i < len(rows):
        if len(rows[i]) < 2:
            i += 1
            continue
        group = [rows[i]]
        j = i + 1
        while j < len(rows) and len(rows[j]) == len(rows[i]):
            tol = max(l.height for l in rows[j]) * 2.5
            prev_gap = rows[j][0].y - max(l.bottom for l in group[-1])
            aligned = all(abs(a.x - b.x) < tol or abs(a.right - b.right) < tol
                          for a, b in zip(group[-1], rows[j]))
            if not aligned or prev_gap > tol * 1.5:
                break
            group.append(rows[j])
            j += 1
        ncols = len(rows[i])
        # 두 칸짜리는 여러 단(단락)과 헷갈리므로, 왼쪽 칸이 짧은 이름표일 때만 표로 본다
        short_left = sum(len(r[0].text) for r in group) / len(group) <= 10
        if (ncols >= 3 and len(group) >= 2) or (ncols == 2 and len(group) >= 3 and short_left):
            blk_lines = [l for r in group for l in r]
            tables.append(Block(blk_lines, kind="table", rows=[[l.text for l in r] for r in group]))
            used.update(id(l) for l in blk_lines)
            i = j
        else:
            i += 1
    rest = [l for l in lines if id(l) not in used]
    return tables, rest


def table_rows(b: Block) -> list[list[Line]]:
    """표 블록의 줄을 행 단위로 다시 나눈다."""
    out, i = [], 0
    for n in (len(r) for r in b.rows):
        out.append(b.lines[i:i + n])
        i += n
    return out


def split_lists(blocks: list[Block]) -> list[Block]:
    """번호·글머리 목록이 시작되거나 끝나는 곳에서 블록을 나눈다.
    목록 항목 아래 들여 쓴 줄은 그 항목에 이어지는 줄로 본다."""
    out = []
    for b in blocks:
        if b.kind == "table":
            out.append(b)
            continue
        cur: list[Line] = []
        in_list = False
        item_x = 0.0
        for l in b.lines:
            is_item = bool(LIST_MARK.match(l.text))
            continuation = in_list and not is_item and l.x > item_x + l.height * 0.5
            state = is_item or continuation
            if cur and state != in_list:
                out.append(Block(cur))
                cur = []
            if is_item:
                item_x = l.x
            in_list = state
            cur.append(l)
        if cur:
            out.append(Block(cur))
    return out


# ---------------------------------------------------------------- 블록 묶기
def group_blocks(lines: list[Line]) -> list[Block]:
    """가로로 겹치고 세로로 가까우며 글자 크기가 비슷한 줄을 한 블록으로 묶는다."""
    lines = sorted(lines, key=lambda l: (l.y, l.x))
    parent = list(range(len(lines)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(lines):
        for j in range(i + 1, len(lines)):
            b = lines[j]
            h = max(a.height, b.height)
            if b.y - a.bottom > 1.2 * h:
                if b.y - a.bottom > 4 * h:
                    break
                continue
            if max(a.height, b.height) / max(1.0, min(a.height, b.height)) > 1.4:
                continue
            x_overlap = min(a.right, b.right) - max(a.x, b.x)
            if x_overlap > -0.5 * h and (b.y - a.bottom) > -0.5 * h:
                parent[find(j)] = find(i)
    groups: dict[int, list[Line]] = {}
    for i, l in enumerate(lines):
        groups.setdefault(find(i), []).append(l)
    return [Block(sorted(g, key=lambda l: (l.y, l.x))) for g in groups.values()]


# ---------------------------------------------------------------- 읽는 순서 (XY-cut)
def _cut(blocks: list[Block], axis: str):
    """axis 방향으로 빈 띠가 있으면 거기서 나눈다."""
    if axis == "y":
        spans = sorted((b.y, b.bottom) for b in blocks)
    else:
        spans = sorted((b.x, b.right) for b in blocks)
    end = spans[0][1]
    for s, e in spans[1:]:
        if s > end:
            mid = (s + end) / 2
            key = (lambda b: b.y) if axis == "y" else (lambda b: b.x)
            first = [b for b in blocks if key(b) < mid]
            second = [b for b in blocks if key(b) >= mid]
            return first, second
        end = max(end, e)
    return None


def reading_order(blocks: list[Block]) -> list[Block]:
    """재귀 XY-cut: 가로 띠로 먼저 나누고(위→아래), 안 되면 세로 단으로 나눈다(왼→오른쪽)."""
    if len(blocks) <= 1:
        return list(blocks)
    for axis in ("y", "x"):
        parts = _cut(blocks, axis)
        if parts:
            return reading_order(parts[0]) + reading_order(parts[1])
    return sorted(blocks, key=lambda b: (b.y, b.x))


# ---------------------------------------------------------------- 문서 구조
def classify(blocks: list[Block], body_height: float) -> None:
    for b in blocks:
        if b.kind == "table":
            continue
        if len(b.lines) <= 3 and b.height >= 1.3 * body_height:
            b.kind = "heading"
        elif sum(1 for l in b.lines if LIST_MARK.match(l.text)) >= max(1, len(b.lines) // 2):
            b.kind = "list"
        else:
            b.kind = "paragraph"


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", text))


def strip_headers_footers(pages: list[Page], margin: float = 0.08) -> None:
    """쪽 번호와 여러 쪽에 반복되는 머리말·꼬리말을 뺀다."""
    def in_margin(b: Block, p: Page) -> bool:
        return b.bottom < p.height * margin or b.y > p.height * (1 - margin)

    counts: dict[str, int] = {}
    for p in pages:
        for key in {_norm(b.text) for b in p.blocks if in_margin(b, p)}:
            counts[key] = counts.get(key, 0) + 1
    repeated = {k for k, c in counts.items() if len(pages) >= 2 and c >= max(2, len(pages) // 2)}
    for p in pages:
        p.blocks = [
            b for b in p.blocks
            if not (in_margin(b, p) and (PAGE_NO.match(b.text) or _norm(b.text) in repeated))
        ]


def build_page(words: list[Word], width: float, height: float, *, find_table: bool = True) -> Page:
    lines = group_lines(words)
    tables, rest = find_tables(lines) if find_table else ([], lines)
    blocks = split_lists(group_blocks(rest)) + tables
    blocks = reading_order(blocks)
    body = median([l.height for l in lines]) if lines else 1
    classify(blocks, body)
    return Page(width=width, height=height, blocks=blocks)
