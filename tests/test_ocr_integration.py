"""실제 Tesseract로 예시 이미지·PDF를 읽는 통합 테스트 (Tesseract와 한글 글꼴이 있을 때만)."""
import sys
from datetime import date
from pathlib import Path

import pytest

from eye import ocr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

pytestmark = pytest.mark.skipif(not ocr.available(), reason="Tesseract OCR이 없음")


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    make = pytest.importorskip("make_samples")
    try:
        make.font(20)
    except SystemExit:
        pytest.skip("한글 글꼴이 없음")
    d = tmp_path_factory.mktemp("samples")
    return make.poster(d / "poster.png"), make.scanned_pdf(d / "scan.pdf")


@pytest.fixture()
def fb(tmp_path):
    from eye.feedback import Feedback

    return Feedback(tmp_path / "fb.json")


def test_image_notice(samples, fb):
    from eye.pipeline import process_image

    res = process_image(samples[0], feedback=fb, ref=date(2026, 11, 18))
    f = res.fields
    assert "진로" in f["title"].value
    assert f["datetime"].dates[0].chosen == date(2026, 12, 3)
    assert "대강당" in f["place"].value
    assert f["deadline"].dates[0].chosen == date(2026, 11, 30)


def test_scanned_pdf(samples, fb, tmp_path):
    from eye.output import full_text, save_searchable_pdf
    from eye.pipeline import process_pdf

    pr = process_pdf(samples[1], feedback=fb)
    res = pr.result
    assert res.document.is_scanned and res.notices
    kinds = [b.kind for b in res.document.pages[0].blocks]
    assert "heading" in kinds and "list" in kinds and "table" in kinds
    text = full_text(res)
    assert "프로세스" in text
    assert "강의자료" not in text  # 반복되는 머리말 제거
    out = save_searchable_pdf(samples[1], pr.page_images, tmp_path / "out.pdf")
    import pymupdf as fitz

    with fitz.open(out) as d:
        assert len(d) == 2 and "상태" in d[0].get_text()
