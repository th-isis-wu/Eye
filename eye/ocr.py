"""③ 글자 인식: 이미지에서 글자를 읽고, 글자마다 내용·위치(좌표)·확신도를 저장한다."""
from __future__ import annotations

import shutil
from typing import Optional

from PIL import Image

from .models import Word

DEFAULT_LANG = "kor+eng"


class OCRUnavailable(RuntimeError):
    pass


def available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _require():
    if not available():
        raise OCRUnavailable(
            "Tesseract OCR을 찾을 수 없습니다. 'tesseract-ocr'와 한국어 데이터('tesseract-ocr-kor')를 설치하세요."
        )
    import pytesseract

    return pytesseract


def recognize(img: Image.Image, *, lang: str = DEFAULT_LANG, psm: int = 11,
              scale: float = 1.0, page: int = 0) -> list[Word]:
    """이미지에서 단어 단위로 글자를 읽는다. 좌표는 scale로 나눠 원본 기준으로 돌려준다."""
    pytesseract = _require()
    data = pytesseract.image_to_data(
        img, lang=lang, config=f"--psm {psm} -c preserve_interword_spaces=1",
        output_type=pytesseract.Output.DICT,
    )
    words: list[Word] = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not text or conf < 0:
            continue
        words.append(Word(
            text=text,
            x=data["left"][i] / scale,
            y=data["top"][i] / scale,
            w=data["width"][i] / scale,
            h=data["height"][i] / scale,
            conf=conf,
            page=page,
        ))
    return words


def quick_word_count(img: Image.Image, lang: str = DEFAULT_LANG, min_conf: float = 50) -> int:
    """감지 단계용: 작게 줄여 빠르게 읽고 확신도 높은 단어 수를 센다."""
    small = img.copy()
    small.thumbnail((1000, 1000))
    try:
        words = recognize(small.convert("L"), lang=lang, psm=11)
    except OCRUnavailable:
        return -1
    return sum(1 for w in words if w.conf >= min_conf and len(w.text) >= 2)


def searchable_pdf_page(img: Image.Image, lang: str = DEFAULT_LANG) -> Optional[bytes]:
    """이미지 한 장을 '글자가 들어간 PDF' 한 쪽으로 만든다."""
    pytesseract = _require()
    return pytesseract.image_to_pdf_or_hocr(img, lang=lang, extension="pdf")
