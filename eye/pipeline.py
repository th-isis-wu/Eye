"""입력 → ①감지 → ②전처리 → ③글자 인식 → ④읽는 순서 → ⑤정보 추출 → ⑥검증 → ⑦출력 연결."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from PIL import Image

from . import detect, ocr
from .extract import extract
from .feedback import Feedback
from .layout import build_page, strip_headers_footers
from .models import Document, Page, Result, Word
from .preprocess import preprocess_image
from .verify import verify

PDF_DPI = 300


@dataclass
class PdfResult:
    result: Result
    page_images: list[Image.Image] = field(default_factory=list)  # 스캔본일 때 보정된 쪽 이미지


def _finish(doc: Document, feedback: Feedback, ref: Optional[date], *, extract_info: bool) -> Result:
    result = Result(document=doc)
    if extract_info:
        result.fields = extract(doc, ref=ref, prefer=feedback.date_preference)
    result.uncertainties = verify(result, threshold=feedback.conf_threshold)
    return result


def ocr_image(img: Image.Image, *, feedback: Feedback, page: int = 0,
              fix_skew: bool = False, psm: int = 11) -> tuple[list[Word], Image.Image, float]:
    prepared, scale = preprocess_image(img, fix_skew=fix_skew)
    words = ocr.recognize(prepared, psm=psm, scale=scale, page=page)
    feedback.apply_corrections(words)
    return words, prepared, scale


def process_image(path: str | Path, *, source_url: Optional[str] = None,
                  feedback: Optional[Feedback] = None, ref: Optional[date] = None,
                  check_text: bool = False) -> Result:
    """이미지 공지(카드뉴스·포스터 캡처)를 읽어 핵심 정보를 뽑는다."""
    feedback = feedback or Feedback()
    path = Path(path)
    img = Image.open(path)
    img.load()
    notices = []
    if check_text and not detect.has_text(img):
        notices.append("이 이미지에서는 글자를 찾지 못했습니다.")
    words, prepared, scale = ocr_image(img, feedback=feedback)
    page = build_page(words, prepared.width / scale, prepared.height / scale)
    doc = Document(source=str(path), kind="image", pages=[page], source_url=source_url)
    result = _finish(doc, feedback, ref, extract_info=True)
    result.notices = notices
    if not words:
        result.notices.append("글자를 읽지 못했습니다.")
    return result


def process_pdf(path: str | Path, *, feedback: Optional[Feedback] = None,
                ref: Optional[date] = None, extract_info: bool = False) -> PdfResult:
    """강의자료 PDF를 읽는다. 글자 정보가 없으면 스캔본으로 알리고 OCR한다."""
    import pymupdf as fitz

    feedback = feedback or Feedback()
    path = Path(path)
    scanned = detect.is_scanned_pdf(path)
    pages: list[Page] = []
    images: list[Image.Image] = []
    with fitz.open(path) as pdf:
        for i, pg in enumerate(pdf):
            if not scanned:
                words = [Word(t, x0, y0, x1 - x0, y1 - y0, 100.0, i, ocr=False)
                         for x0, y0, x1, y1, t, *_ in pg.get_text("words") if t.strip()]
                pages.append(build_page(words, pg.rect.width, pg.rect.height))
                continue
            # 페이지별 이미지로 나누고 기울기·그림자 보정 후 OCR
            pix = pg.get_pixmap(matrix=fitz.Matrix(PDF_DPI / 72, PDF_DPI / 72), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            words, prepared, scale = ocr_image(img, feedback=feedback, page=i, fix_skew=True, psm=3)
            images.append(prepared)
            pages.append(build_page(words, prepared.width / scale, prepared.height / scale))
    strip_headers_footers(pages)
    doc = Document(source=str(path), kind="pdf", pages=pages, is_scanned=scanned)
    result = _finish(doc, feedback, ref, extract_info=extract_info)
    if scanned:
        result.notices.append("스캔본입니다. 글자 정보가 없어 글자 인식(OCR)으로 읽었습니다.")
    return PdfResult(result, images)
