"""OCR 없이 돌아가는 단위 테스트: 날짜, 읽는 순서, 정보 추출, 검증, 피드백."""
from datetime import date

import pytest

from eye.dates import find_dates, find_times, format_date, format_time
from eye.extract import extract
from eye.feedback import Feedback
from eye.layout import build_page, group_lines, reading_order, group_blocks, strip_headers_footers
from eye.models import Document, Page, Result, Word
from eye.verify import apply_date_choice, verify

REF = date(2026, 11, 18)


def W(text, x, y, h=20, conf=95.0, w=None):
    return Word(text, x, y, w if w is not None else len(text) * h * 0.9, h, conf)


def doc_from_rows(rows, h=20):
    """[(텍스트, x, y), ...] 로 문서를 만든다. 텍스트는 띄어쓰기 단위로 단어를 만든다."""
    words = []
    for text, x, y, *rest in rows:
        hh = rest[0] if rest else h
        cx = x
        for t in text.split():
            words.append(Word(t, cx, y, len(t) * hh * 0.9, hh, 95.0, ocr=False))
            cx += len(t) * hh * 0.9 + hh * 0.5
    return Document("test", pages=[build_page(words, 1000, 1400)])


# ------------------------------------------------------------------ 날짜
class TestDates:
    def test_full_date_is_certain(self):
        r = find_dates("2026.12.3(목) 오후 2시", REF)[0]
        assert r.chosen == date(2026, 12, 3) and r.certain

    def test_korean_month_day(self):
        r = find_dates("12월 3일(목)", REF)[0]
        assert r.chosen == date(2026, 12, 3) and r.certain

    def test_slash_date_without_weekday_is_ambiguous(self):
        r = find_dates("12/03", REF)[0]
        assert not r.certain
        assert r.options == [date(2026, 12, 3), date(2027, 3, 12)]

    def test_weekday_resolves_ambiguity(self):
        r = find_dates("12/03(목)", REF)[0]
        assert r.certain and r.chosen == date(2026, 12, 3)
        r = find_dates("3/12(목)", REF)[0]  # 2027-03-12는 금요일 → 12월 3일로 판단
        assert r.certain and r.chosen == date(2026, 12, 3)

    def test_weekday_mismatch_flagged(self):
        r = find_dates("12월 3일(수)", REF)[0]
        assert not r.certain and "요일" in r.reason

    def test_preference_dm(self):
        r = find_dates("12/03", REF, prefer="DM")[0]
        assert r.chosen == date(2027, 3, 12)

    def test_day_over_12_is_unambiguous(self):
        r = find_dates("25/12", REF)[0]
        assert r.certain and r.chosen == date(2026, 12, 25)

    def test_decimal_is_not_date(self):
        assert find_dates("평점 4.5점", REF) == []

    def test_times(self):
        assert find_times("14:00~16:00") == ["14:00", "16:00"]
        assert find_times("오후 2시 30분") == ["14:30"]
        assert find_times("오전 10시 반") == ["10:30"]
        assert find_times("3시간 동안") == []

    def test_format(self):
        assert format_date(date(2026, 12, 3)) == "2026년 12월 3일 목요일"
        assert format_time("14:00") == "오후 2시"
        assert format_time("09:30") == "오전 9시 30분"


# ------------------------------------------------------------------ 읽는 순서
class TestLayout:
    def test_lines_and_columns(self):
        words = [W("왼쪽", 0, 0), W("단", 50, 0), W("오른쪽", 500, 0)]
        lines = group_lines(words)
        assert [l.text for l in lines] == ["왼쪽 단", "오른쪽"]

    def test_two_columns_read_left_then_right(self):
        rows = [("제목입니다", 0, 0, 40)]
        rows += [(f"왼쪽 단의 {i}번째 줄은 이렇게 길게 이어집니다", 0, 100 + i * 30) for i in range(4)]
        rows += [(f"오른쪽 단의 {i}번째 줄도 길게 이어집니다", 600, 100 + i * 30) for i in range(4)]
        doc = doc_from_rows(rows)
        text = [b.text for b in doc.blocks]
        assert text[0] == "제목입니다"
        assert text[1].startswith("왼쪽 단의 0") and "왼쪽 단의 3" in text[1] and "오른쪽" not in text[1]
        assert text[2].startswith("오른쪽 단의 0")
        assert doc.blocks[0].kind == "heading"

    def test_table_detected(self):
        rows = [("이름", 0, 0), ("학번", 300, 0), ("학과", 600, 0),
                ("홍길동", 0, 40), ("2026001", 300, 40), ("컴퓨터", 600, 40),
                ("김철수", 0, 80), ("2026002", 300, 80), ("전자", 600, 80)]
        doc = doc_from_rows(rows)
        tables = [b for b in doc.blocks if b.kind == "table"]
        assert len(tables) == 1
        assert tables[0].rows[1] == ["홍길동", "2026001", "컴퓨터"]

    def test_list_detected(self):
        doc = doc_from_rows([("설명 문단입니다", 0, 0), ("1. 첫째", 0, 30), ("2. 둘째", 0, 60)])
        kinds = [b.kind for b in doc.blocks]
        assert kinds == ["paragraph", "list"]

    def test_xy_cut_order(self):
        blocks = group_blocks(group_lines([W("B", 500, 0), W("A", 0, 0), W("C", 0, 300)]))
        assert [b.text for b in reading_order(blocks)] == ["A", "B", "C"]

    def test_page_numbers_and_repeated_headers_removed(self):
        pages = []
        for n in (1, 2, 3):
            words = [Word("강의자료", 0, 5, 80, 20, ocr=False),
                     Word(f"본문{n}", 0, 500, 60, 20, ocr=False),
                     Word(f"- {n} -", 400, 1370, 40, 20, ocr=False)]
            pages.append(build_page(words, 1000, 1400))
        strip_headers_footers(pages)
        assert [[b.text for b in p.blocks] for p in pages] == [["본문1"], ["본문2"], ["본문3"]]

    def test_korean_ocr_fragments_joined(self):
        words = [W("학", 0, 0, w=20), W("생", 22, 0, w=20), W("회", 44, 0, w=20), W("관", 66, 0, w=20),
                 W("3층", 100, 0, w=40)]
        assert group_lines(words)[0].text == "학생회관 3층"


# ------------------------------------------------------------------ 정보 추출 + 검증
POSTER = [
    ("2026 진로 특강", 50, 50, 60),
    ("일시: 12/03(목) 14:00~16:00", 50, 200),
    ("장소: 학생회관 3층 대강당", 50, 250),
    ("신청 방법: 구글폼 forms.gle/abc123", 50, 300),
    ("신청 마감: 11/30(월)까지", 50, 350),
]


class TestExtract:
    def test_labeled_fields(self):
        f = extract(doc_from_rows(POSTER), ref=REF)
        assert f["title"].value == "2026 진로 특강"
        assert f["datetime"].value == "2026년 12월 3일 목요일 오후 2시부터 오후 4시까지"
        assert f["place"].value == "학생회관 3층 대강당"
        assert "forms.gle/abc123" in f["apply"].value
        assert f["deadline"].value == "2026년 11월 30일 월요일"
        assert not any(x.uncertain for x in f.values())

    def test_unlabeled_fields(self):
        doc = doc_from_rows([
            ("코딩 동아리 신입 모집", 50, 50, 50),
            ("12월 10일(목) 오후 7시", 50, 200),
            ("공학관 101호", 50, 250),
            ("11월 30일(월)까지 신청", 50, 300),
            ("bit.ly/code-club", 50, 350),
        ])
        f = extract(doc, ref=REF)
        assert f["title"].value == "코딩 동아리 신입 모집"
        assert f["datetime"].value.startswith("2026년 12월 10일 목요일")
        assert f["place"].value == "공학관 101호"
        assert f["deadline"].value == "2026년 11월 30일 월요일"
        assert "bit.ly" in f["apply"].value

    def test_label_on_next_line(self):
        doc = doc_from_rows([("장소", 50, 0), ("온라인 Zoom", 50, 30)])
        assert extract(doc, ref=REF)["place"].value == "온라인 Zoom"


class TestVerify:
    def test_ambiguous_date_reported_and_resolved(self):
        rows = [("행사명: 송년회", 0, 0), ("일시: 12/03 18:00", 0, 40)]
        doc = doc_from_rows(rows)
        res = Result(doc, extract(doc, ref=REF))
        us = verify(res)
        amb = [u for u in us if u.kind == "ambiguous_date"]
        assert len(amb) == 1 and len(amb[0].options) == 2
        f = res.fields["datetime"]
        assert f.uncertain and "확실하지 않음" in f.value
        apply_date_choice(f, 0, 1)
        assert f.value == "2027년 3월 12일 금요일 오후 6시" and not f.uncertain

    def test_low_confidence_word_linked_to_field(self):
        doc = doc_from_rows([("장소: 공학관", 0, 0)])
        doc.words[-1].conf = 30
        res = Result(doc, extract(doc, ref=REF))
        us = verify(res, threshold=60)
        assert [u.text for u in us] == ["공학관"]
        assert us[0].field_name == "place" and res.fields["place"].uncertain

    def test_confusable_digit_letter(self):
        doc = doc_from_rows([("12/O3", 0, 0)])
        doc.words[0].conf = 80
        assert any("숫자" in u.message for u in verify(Result(doc)))


# ------------------------------------------------------------------ 피드백
class TestFeedback:
    def test_corrections_applied_next_time(self, tmp_path):
        fb = Feedback(tmp_path / "fb.json")
        fb.record_word("몽사활동", "봉사활동")
        fb2 = Feedback(tmp_path / "fb.json")
        words = [Word("몽사활동", 0, 0, 10, 10, 40)]
        assert fb2.apply_corrections(words) == 1
        assert words[0].text == "봉사활동" and words[0].conf >= 95

    def test_date_preference_learned(self, tmp_path):
        fb = Feedback(tmp_path / "fb.json")
        assert fb.date_preference == "MD"
        fb.record_date_choice("03/12", "DM", "2026-12-03")
        assert fb.date_preference == "MD"  # 한 번으로는 바꾸지 않음
        fb.record_date_choice("05/12", "DM", "2026-12-05")
        assert fb.date_preference == "DM"

    def test_threshold_adapts(self, tmp_path):
        fb = Feedback(tmp_path / "fb.json")
        for _ in range(6):
            fb.record_word("a", "a")  # 표시했지만 맞았음
        assert fb.conf_threshold < 60
        fb.reset()
        for _ in range(6):
            fb.record_word("a", "b")  # 표시한 것이 실제로 틀렸음
        assert fb.conf_threshold > 60


def test_cli_parser():
    from eye.cli import build_parser

    a = build_parser().parse_args(["--no-voice", "image", "x.png", "--url", "https://example.com"])
    assert a.cmd == "image" and a.url == "https://example.com"


if __name__ == "__main__":
    pytest.main([__file__])
