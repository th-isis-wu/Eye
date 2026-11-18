"""명령줄 앱. 화면낭독기와 음성으로 쓰기 쉽도록 번호 메뉴만 사용한다."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, detect, ocr
from .feedback import Feedback, data_dir
from .inbox import Inbox
from .models import Result
from .output import Speaker, full_text, open_original, save_searchable_pdf, save_text, summary_lines
from .pipeline import process_image, process_pdf
from .verify import apply_date_choice

DEFAULT_WATCH = ["~/Pictures/Screenshots", "~/Pictures", "~/Desktop", "~/Downloads"]


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "0"


# ------------------------------------------------------------------ 불확실 항목 선택
def resolve_uncertainties(result: Result, fb: Feedback, sp: Speaker) -> None:
    pending = [u for u in result.uncertainties if not u.resolved]
    if not pending:
        sp.say("확실하지 않은 항목이 없습니다.")
        return
    for u in pending:
        sp.say(u.message)
        if u.kind == "ambiguous_date" and u.reading is not None:
            for i, opt in enumerate(u.options, 1):
                sp.say(f"{i}번, {opt}")
            ans = _ask("번호를 고르세요 (Enter=건너뛰기): ")
            if ans.isdigit() and 1 <= int(ans) <= len(u.options):
                choice = int(ans) - 1
                f = result.fields[u.field_name]
                idx = f.dates.index(u.reading)
                r = u.reading
                picked = r.options[choice]
                order = "MD" if picked.month == _first_num(r.raw) else "DM"
                apply_date_choice(f, idx, choice)
                fb.record_date_choice(r.raw, order, picked.isoformat())
                u.resolved, u.chosen = True, u.options[choice]
                sp.say(f"{u.options[choice]}(으)로 기록했습니다.")
        elif u.kind == "low_conf" and u.word is not None:
            ans = _ask(f"'{u.text}' — 맞으면 Enter, 틀리면 바른 글자를 입력하세요: ")
            if ans == "0":
                break
            fb.record_word(u.text, ans)
            if ans and ans != u.text:
                u.word.text = ans
                for f in result.fields.values():
                    f.value = f.value.replace(u.text, ans)
                sp.say(f"'{ans}'(으)로 고쳤습니다. 다음부터 자동으로 고칩니다.")
            u.resolved = True
    for f in result.fields.values():
        f.uncertain = any(not u.resolved and u.field_name == f.name for u in result.uncertainties)


def _first_num(raw: str) -> int:
    import re

    m = re.match(r"\s*(\d+)", raw)
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------ 메뉴
def image_menu(result: Result, fb: Feedback, sp: Speaker) -> None:
    while True:
        sp.say("1 핵심 정보, 2 불확실 항목 선택, 3 전체 읽기, 4 원래 게시글 열기, 0 끝내기")
        ans = _ask("> ")
        if ans == "1":
            sp.say_lines(summary_lines(result))
        elif ans == "2":
            resolve_uncertainties(result, fb, sp)
        elif ans == "3":
            sp.say(full_text(result, spoken=True))
        elif ans == "4":
            sp.say(f"원래 게시글을 엽니다: {open_original(result)}")
        elif ans in ("0", "q"):
            return


def pdf_menu(result: Result, fb: Feedback, sp: Speaker) -> None:
    while True:
        sp.say("1 차례대로 읽기, 2 불확실 항목 선택, 0 끝내기")
        ans = _ask("> ")
        if ans == "1":
            for page_i, page in enumerate(result.document.pages, 1):
                sp.say(f"{page_i}쪽")
                sub = Result(document=type(result.document)(source=result.document.source, pages=[page]),
                             uncertainties=result.uncertainties)
                for para in full_text(sub, spoken=True).split("\n\n"):
                    sp.say(para)
                    if _ask("(Enter=다음, 0=멈춤) ") == "0":
                        return
        elif ans == "2":
            resolve_uncertainties(result, fb, sp)
        elif ans in ("0", "q"):
            return


def result_json(result: Result) -> dict:
    return {
        "source": result.document.source,
        "kind": result.document.kind,
        "scanned": result.document.is_scanned,
        "notices": result.notices,
        "fields": {k: {"value": f.value, "raw": f.raw, "uncertain": f.uncertain,
                       "dates": [d.chosen.isoformat() for d in f.dates if d.chosen]}
                   for k, f in result.fields.items()},
        "uncertainties": [{"kind": u.kind, "text": u.text, "message": u.message, "options": u.options}
                          for u in result.uncertainties],
        "blocks": [{"kind": b.kind, "text": b.text, **({"rows": b.rows} if b.rows else {})}
                   for b in result.document.blocks],
    }


# ------------------------------------------------------------------ 명령
def cmd_image(a, fb: Feedback, sp: Speaker) -> int:
    result = process_image(a.path, source_url=a.url, feedback=fb)
    if a.json:
        print(json.dumps(result_json(result), ensure_ascii=False, indent=2))
        return 0
    sp.say_lines(result.notices)
    sp.say_lines(summary_lines(result))
    if a.save:
        sp.say(f"저장했습니다: {save_text(result, Path(a.save))}")
    if not a.no_menu:
        image_menu(result, fb, sp)
    return 0


def cmd_pdf(a, fb: Feedback, sp: Speaker) -> int:
    src = Path(a.path)
    pr = process_pdf(src, feedback=fb)
    result = pr.result
    if a.json:
        print(json.dumps(result_json(result), ensure_ascii=False, indent=2))
        return 0
    sp.say_lines(result.notices)
    out_dir = Path(a.out or src.parent)
    txt = save_text(result, out_dir / f"{src.stem}.읽기용.txt")
    pdf = save_searchable_pdf(src, pr.page_images, out_dir / f"{src.stem}.읽기용.pdf")
    n = sum(1 for u in result.uncertainties if u.kind == "low_conf")
    sp.say(f"{len(result.document.pages)}쪽 문서를 읽을 수 있는 문서로 저장했습니다.")
    sp.say(f"텍스트: {txt}")
    sp.say(f"PDF: {pdf}")
    if n:
        sp.say(f"확실하지 않은 글자 {n}개를 [?글자]로 표시했습니다.")
    if not a.no_menu:
        pdf_menu(result, fb, sp)
    return 0


def cmd_watch(a, fb: Feedback, sp: Speaker) -> int:
    folders = a.folders or DEFAULT_WATCH
    w = detect.Watcher(folders, only_captures=a.captures_only)
    if not a.include_existing:
        w.mark_existing()
    inbox = Inbox()
    out_dir = Path(a.out).expanduser() if a.out else data_dir() / "outputs"
    sp.say("새 캡처와 PDF를 기다립니다. 멈추려면 Ctrl+C를 누르세요.")
    sp.say("살펴보는 폴더: " + ", ".join(str(f) for f in w.folders if f.is_dir()))

    def on_new(p: Path) -> None:
        kind = detect.kind_of(p)
        try:
            if kind == "image":
                from PIL import Image

                with Image.open(p) as img:
                    img.load()
                    if not detect.has_text(img):
                        return
                result = process_image(p, feedback=fb)
                summary = summary_lines(result)
                txt = save_text(result, out_dir / f"{p.stem}.txt")
                inbox.add(str(p), kind, summary, str(txt))
                sp.say("새 이미지 공지가 있습니다.")
                sp.say_lines(summary)
            elif kind == "pdf":
                pr = process_pdf(p, feedback=fb)
                txt = save_text(pr.result, out_dir / f"{p.stem}.읽기용.txt")
                save_searchable_pdf(p, pr.page_images, out_dir / f"{p.stem}.읽기용.pdf")
                inbox.add(str(p), kind, pr.result.notices, str(txt))
                sp.say(f"새 강의자료가 올라왔습니다: {p.name}")
                sp.say_lines(pr.result.notices)
        except Exception as e:
            sp.say(f"{p.name}을(를) 읽지 못했습니다: {e}")

    try:
        w.run(on_new, interval=a.interval)
    except KeyboardInterrupt:
        sp.say("감시를 멈췄습니다.")
    return 0


def cmd_inbox(a, fb: Feedback, sp: Speaker) -> int:
    inbox = Inbox()
    items = inbox.unread()
    if not items:
        sp.say("안 읽은 공지가 없습니다.")
        return 0
    sp.say(f"안 읽은 공지가 {len(items)}개 있습니다.")
    for item in items:
        sp.say(f"{Path(item['source']).name}")
        sp.say_lines(item["summary"])
        if item.get("output"):
            sp.say(f"전체 글: {item['output']}")
        inbox.mark_read(item["source"])
        if not a.all and _ask("(Enter=다음, 0=멈춤) ") == "0":
            break
    return 0


def cmd_feedback(a, fb: Feedback, sp: Speaker) -> int:
    if a.action == "reset":
        fb.reset()
        sp.say("학습 기록을 지웠습니다.")
        return 0
    d = fb.data
    print(f"기록 파일: {fb.path}")
    print(f"날짜 읽는 순서: {'월/일' if fb.date_preference == 'MD' else '일/월'} "
          f"(월/일 {d['date_order'].get('MD', 0)}회, 일/월 {d['date_order'].get('DM', 0)}회)")
    print(f"불확실 기준 확신도: {fb.conf_threshold:.0f}%")
    print(f"자동으로 고치는 글자 {len(d['corrections'])}개")
    for k, v in d["corrections"].items():
        print(f"  {k} → {v}")
    return 0


def cmd_check(a, fb: Feedback, sp: Speaker) -> int:
    print(f"eye {__version__}")
    print(f"Tesseract OCR: {'사용 가능' if ocr.available() else '없음 (설치 필요)'}")
    try:
        import pymupdf  # noqa: F401
        print("PyMuPDF: 사용 가능")
    except ImportError:
        print("PyMuPDF: 없음 (pip install pymupdf)")
    print(f"음성: {Speaker().backend}")
    print(f"데이터 폴더: {data_dir()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eye", description="이미지 공지와 스캔 강의자료를 읽어 주는 접근성 도우미")
    p.add_argument("--no-voice", action="store_true", help="음성 없이 글로만 출력")
    p.add_argument("--rate", type=int, default=170, help="말하기 속도")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("image", help="이미지 공지(캡처) 읽기")
    s.add_argument("path")
    s.add_argument("--url", help="원래 게시글 주소")
    s.add_argument("--save", help="읽은 내용을 텍스트로 저장할 경로")
    s.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    s.add_argument("--no-menu", action="store_true", help="메뉴 없이 핵심 정보만 읽고 끝내기")
    s.set_defaults(func=cmd_image)

    s = sub.add_parser("pdf", help="강의자료 PDF를 읽을 수 있는 문서로 만들기")
    s.add_argument("path")
    s.add_argument("-o", "--out", help="저장할 폴더 (기본: PDF와 같은 폴더)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-menu", action="store_true")
    s.set_defaults(func=cmd_pdf)

    s = sub.add_parser("watch", help="새 캡처·PDF가 생기면 자동으로 읽기")
    s.add_argument("folders", nargs="*")
    s.add_argument("--interval", type=float, default=2.0)
    s.add_argument("--out", help="결과를 저장할 폴더")
    s.add_argument("--captures-only", action="store_true", help="이름이 캡처/스크린샷인 이미지만")
    s.add_argument("--include-existing", action="store_true", help="이미 있던 파일도 읽기")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("inbox", help="안 읽은 공지 듣기")
    s.add_argument("--all", action="store_true", help="멈추지 않고 모두 읽기")
    s.set_defaults(func=cmd_inbox)

    s = sub.add_parser("feedback", help="학습 기록 보기/지우기")
    s.add_argument("action", nargs="?", choices=["show", "reset"], default="show")
    s.set_defaults(func=cmd_feedback)

    s = sub.add_parser("check", help="필요한 프로그램이 설치됐는지 확인")
    s.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    sp = Speaker(enabled=not a.no_voice and not getattr(a, "json", False), rate=a.rate)
    fb = Feedback()
    try:
        return a.func(a, fb, sp)
    except ocr.OCRUnavailable as e:
        print(e, file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"파일을 찾을 수 없습니다: {e.filename}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
