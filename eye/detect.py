"""① 감지: 새 캡처·PDF가 생기면 자동 실행, 글자가 있는 이미지인지 / 스캔본인지 판단."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from PIL import Image

from . import ocr
from .feedback import data_dir
from .preprocess import text_region_ratio

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}
PDF_EXT = {".pdf"}
CAPTURE_NAME = re.compile(r"screen\s*shot|screenshot|스크린샷|캡처|capture|kakaotalk|insta", re.IGNORECASE)


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in PDF_EXT:
        return "pdf"
    return None


def is_capture(path: Path) -> bool:
    return bool(CAPTURE_NAME.search(path.name))


def has_text(img: Image.Image) -> bool:
    """글자가 있는 이미지인지 판단한다 (빠른 경계 검사 → 빠른 OCR)."""
    if text_region_ratio(img) < 0.02:
        return False
    n = ocr.quick_word_count(img)
    return n < 0 or n >= 3  # OCR이 없으면 일단 처리 대상으로 본다


def pdf_text_stats(path: Path) -> list[int]:
    """쪽마다 PDF에 들어 있는 글자 수."""
    import pymupdf as fitz

    with fitz.open(path) as doc:
        return [len(page.get_text("text").strip()) for page in doc]


def is_scanned_pdf(path: Path, min_chars: int = 30) -> bool:
    """PDF에 글자 정보가 없으면(쪽 대부분이 이미지뿐이면) 스캔본이다."""
    stats = pdf_text_stats(path)
    if not stats:
        return False
    empty = sum(1 for c in stats if c < min_chars)
    return empty >= max(1, len(stats) / 2)


class Watcher:
    """폴더를 주기적으로 살펴 새 이미지·PDF를 찾는다. 처리한 파일은 기억한다."""

    def __init__(self, folders: Iterable[Path], state_path: Path | None = None, only_captures: bool = False):
        self.folders = [Path(f).expanduser() for f in folders]
        self.state_path = state_path or data_dir() / "seen.json"
        self.only_captures = only_captures
        self.seen: dict[str, float] = {}
        if self.state_path.exists():
            try:
                self.seen = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.seen = {}

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.seen, ensure_ascii=False), encoding="utf-8")

    def mark_existing(self) -> None:
        """처음 시작할 때 이미 있던 파일은 건너뛴다."""
        for p in self._files():
            self.seen[str(p)] = p.stat().st_mtime
        self._save()

    def _files(self) -> Iterator[Path]:
        for folder in self.folders:
            if not folder.is_dir():
                continue
            for p in folder.iterdir():
                if p.is_file() and kind_of(p) and not p.name.startswith("."):
                    if self.only_captures and kind_of(p) == "image" and not is_capture(p):
                        continue
                    yield p

    def poll(self) -> list[Path]:
        new = []
        for p in self._files():
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if self.seen.get(str(p)) == mtime:
                continue
            if time.time() - mtime < 1.0:  # 아직 저장 중일 수 있다
                continue
            self.seen[str(p)] = mtime
            new.append(p)
        if new:
            self._save()
        return sorted(new, key=lambda p: p.stat().st_mtime)

    def run(self, on_new: Callable[[Path], None], interval: float = 2.0,
            stop: Callable[[], bool] = lambda: False) -> None:
        while not stop():
            for p in self.poll():
                on_new(p)
            time.sleep(interval)
