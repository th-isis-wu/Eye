"""예시 이미지 공지와 스캔본 PDF를 만든다: python examples/make_samples.py"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    sys.exit("한글 글꼴을 찾을 수 없습니다 (예: fonts-nanum 설치).")


def poster(path: Path) -> Path:
    img = Image.new("RGB", (1080, 1350), (250, 244, 230))
    d = ImageDraw.Draw(img)
    for i in range(0, 1080, 60):  # 배경 장식
        d.ellipse((i, 40, i + 30, 70), fill=(240, 200, 150))
    d.text((80, 140), "2026 진로 특강", font=font(96), fill=(30, 30, 60))
    d.text((80, 260), "AI 시대의 커리어 설계", font=font(56), fill=(60, 60, 90))
    y = 460
    for line in ["일시: 12/03(목) 14:00~16:00", "장소: 학생회관 3층 대강당",
                 "신청 방법: 구글폼 forms.gle/abc123", "신청 마감: 11/30(월)까지"]:
        d.text((80, y), line, font=font(48), fill=(20, 20, 20))
        y += 110
    d.text((80, 1180), "주최: 학생처 진로지원센터", font=font(36), fill=(90, 90, 90))
    img.save(path)
    return path


def scanned_pdf(path: Path) -> Path:
    pages = []
    for n in (1, 2):
        img = Image.new("L", (1654, 2339), 255)  # A4, 200dpi
        d = ImageDraw.Draw(img)
        d.text((150, 60), "운영체제 강의자료", font=font(30), fill=0)
        d.text((150, 200), f"{n}장. 프로세스와 스레드" if n == 1 else f"{n}장. 스케줄링", font=font(64), fill=0)
        y = 360
        for t in ["프로세스는 실행 중인 프로그램이다.", "운영체제는 자원을 나누어 준다.",
                  "1. 생성 상태", "2. 준비 상태", "3. 실행 상태"]:
            d.text((150, y), t, font=font(40), fill=0)
            y += 80
        y += 40
        for row in [("상태", "설명", "예시"), ("준비", "CPU를 기다림", "대기열"), ("실행", "CPU 사용 중", "코어")]:
            for x, cell in zip((150, 600, 1100), row):
                d.text((x, y), cell, font=font(40), fill=0)
            y += 80
        d.text((800, 2230), f"- {n} -", font=font(30), fill=0)
        img = img.rotate(1.2, fillcolor=255, expand=False).filter(ImageFilter.GaussianBlur(0.6))
        pages.append(img.convert("RGB"))
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=200)
    return path


if __name__ == "__main__":
    print(poster(HERE / "sample_poster.png"))
    print(scanned_pdf(HERE / "sample_scanned.pdf"))
