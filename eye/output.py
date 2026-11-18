"""⑦ 출력: 음성 안내(핵심 정보 먼저, 전체 읽기), 원래 게시글 연결, 읽을 수 있는 문서로 저장."""
from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image

from .extract import FIELD_NAMES
from .layout import table_rows
from .models import Block, Result, Word


# ------------------------------------------------------------------ 글로 만들기
def summary_lines(result: Result) -> list[str]:
    """핵심 정보 먼저: 행사명 → 일시 → 장소 → 신청 방법 → 마감."""
    out = []
    for key, label in FIELD_NAMES.items():
        f = result.fields.get(key)
        if f is None:
            continue
        mark = " (확실하지 않음)" if f.uncertain and "확실하지 않음" not in f.value else ""
        out.append(f"{label}: {f.value}{mark}")
    if not out:
        out.append("행사 정보를 찾지 못했습니다. 전체 읽기를 선택하세요.")
    n = sum(1 for u in result.uncertainties if not u.resolved)
    if n:
        out.append(f"확실하지 않은 항목이 {n}개 있습니다.")
    return out


def _marker(result: Result, spoken: bool) -> Callable[[Word], str]:
    ids = {id(u.word) for u in result.uncertainties if u.kind == "low_conf" and not u.resolved and u.word}
    if spoken:
        return lambda w: f"(확실하지 않은 글자, {w.text})" if id(w) in ids else w.text
    return lambda w: f"[?{w.text}]" if id(w) in ids else w.text


def block_text(b: Block, *, spoken: bool = False, fmt: Optional[Callable[[Word], str]] = None) -> str:
    if b.kind == "table":
        rows = [[l.render(fmt) for l in r] for r in table_rows(b)] if fmt else (b.rows or [[l.text] for l in b.lines])
        head = f"표 시작, {len(rows)}행 {max(len(r) for r in rows)}열" if spoken else "[표]"
        body = [f"{i}행: " + (", " if spoken else " | ").join(r) for i, r in enumerate(rows, 1)]
        tail = ["표 끝"] if spoken else []
        return "\n".join([head, *body, *tail])
    if b.kind == "heading":
        return ("제목, " if spoken else "# ") + " ".join(l.render(fmt) for l in b.lines)
    if b.kind == "list":
        return "\n".join(("목록, " if spoken else "") + l.render(fmt) for l in b.lines)
    return " ".join(l.render(fmt) for l in b.lines)


def full_text(result: Result, *, spoken: bool = False, mark: bool = True) -> str:
    """읽는 순서대로 정리한 전체 글. 불확실한 글자는 [?글자]로 표시한다."""
    doc = result.document
    parts = []
    for i, page in enumerate(doc.pages, 1):
        if len(doc.pages) > 1:
            parts.append(f"{i}쪽" if spoken else f"--- {i}쪽 ---")
        fmt = _marker(result, spoken) if mark else None
        parts.extend(block_text(b, spoken=spoken, fmt=fmt) for b in page.blocks)
    return "\n\n".join(parts)


# ------------------------------------------------------------------ 음성
class Speaker:
    """pyttsx3 → espeak-ng → 화면 출력 순서로 가능한 방법을 쓴다."""

    def __init__(self, enabled: bool = True, rate: int = 170):
        self.enabled = enabled
        self.rate = rate
        self.engine = None
        self.backend = "print"
        if not enabled:
            return
        try:
            import pyttsx3

            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", rate)
            for v in self.engine.getProperty("voices") or []:
                langs = " ".join(str(x) for x in (getattr(v, "languages", []) or []))
                if "ko" in langs.lower() or "korean" in (v.name or "").lower():
                    self.engine.setProperty("voice", v.id)
                    break
            self.backend = "pyttsx3"
        except Exception:  # 음성 엔진이 없는 환경
            self.engine = None
            for cmd in ("espeak-ng", "espeak", "say"):
                if shutil.which(cmd):
                    self.backend = cmd
                    break

    def say(self, text: str) -> None:
        print(text, flush=True)
        if not self.enabled or not text.strip():
            return
        try:
            if self.backend == "pyttsx3":
                self.engine.say(text)
                self.engine.runAndWait()
            elif self.backend in ("espeak-ng", "espeak"):
                subprocess.run([self.backend, "-v", "ko", "-s", str(self.rate), text],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            elif self.backend == "say":
                subprocess.run(["say", text], check=False)
        except Exception as e:  # 음성이 실패해도 글은 이미 보여줬다
            print(f"(음성 출력 실패: {e})", file=sys.stderr)

    def say_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.say(line)


# ------------------------------------------------------------------ 저장·연결
def save_text(result: Result, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    if result.notices:
        body += [f"※ {n}" for n in result.notices] + [""]
    if result.fields:
        body += summary_lines(result) + [""]
    body.append(full_text(result))
    out_path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return out_path


def save_searchable_pdf(source_pdf: Path, page_images: list[Image.Image], out_path: Path) -> Path:
    """스캔본이면 쪽마다 OCR 글자 층을 넣은 PDF를 만들고, 원래 글자가 있으면 그대로 복사한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not page_images:
        shutil.copyfile(source_pdf, out_path)
        return out_path
    import pymupdf as fitz

    from . import ocr

    merged = fitz.open()
    for img in page_images:
        data = ocr.searchable_pdf_page(img)
        with fitz.open("pdf", data) as one:
            merged.insert_pdf(one)
    merged.save(out_path)
    merged.close()
    return out_path


def open_original(result: Result) -> Optional[str]:
    """원래 게시글(주소가 있으면 주소, 없으면 원본 파일)을 연다."""
    target = result.document.source_url or Path(result.document.source).resolve().as_uri()
    try:
        webbrowser.open(target)
    except Exception:
        pass
    return target
