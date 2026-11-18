"""② 전처리: 확대, 대비 보정, 배경 장식 줄이기, 기울기·그림자 보정."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

TARGET_MIN_WIDTH = 1800  # 이보다 작은 캡처는 확대한다


def to_gray(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return img.convert("L")


def upscale(img: Image.Image, min_width: int = TARGET_MIN_WIDTH) -> tuple[Image.Image, float]:
    """작은 캡처를 확대한다. (이미지, 배율)을 돌려준다."""
    if img.width >= min_width:
        return img, 1.0
    scale = min(4.0, min_width / img.width)
    size = (round(img.width * scale), round(img.height * scale))
    return img.resize(size, Image.LANCZOS), scale


def remove_shadow(gray: Image.Image) -> Image.Image:
    """배경(그림자, 그라데이션)을 크게 흐린 이미지로 나눠 고르게 만든다."""
    radius = max(15, min(gray.size) // 30)
    bg = gray.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(radius))
    a = np.asarray(gray, dtype=np.float32)
    b = np.asarray(bg, dtype=np.float32) + 1.0
    out = np.clip(a / b * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


def is_dark_background(gray: Image.Image) -> bool:
    """카드뉴스처럼 어두운 배경에 밝은 글자인지 (가장자리 밝기로 판단)."""
    a = np.asarray(gray)
    edge = np.concatenate([a[:5].ravel(), a[-5:].ravel(), a[:, :5].ravel(), a[:, -5:].ravel()])
    return float(np.median(edge)) < 110


def otsu_threshold(gray: Image.Image) -> int:
    hist = np.bincount(np.asarray(gray).ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    sum_all = np.dot(np.arange(256), hist)
    w_b = sum_b = 0.0
    best, best_t = -1.0, 127
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best:
            best, best_t = between, t
    return best_t


def binarize(gray: Image.Image) -> Image.Image:
    t = otsu_threshold(gray)
    return gray.point(lambda v: 255 if v > t else 0, mode="L")


def estimate_skew(gray: Image.Image, max_angle: float = 6.0, step: float = 0.5) -> float:
    """가로 투영 분산이 가장 큰 각도를 찾아 기울기를 추정한다(도)."""
    small = gray.copy()
    small.thumbnail((800, 800))
    ink = ImageOps.invert(binarize(small))
    best_angle, best_score = 0.0, -1.0
    angle = -max_angle
    while angle <= max_angle + 1e-9:
        rot = np.asarray(ink.rotate(angle, resample=Image.BILINEAR, fillcolor=0), dtype=np.float32)
        score = float(np.var(rot.sum(axis=1)))
        if score > best_score:
            best_score, best_angle = score, angle
        angle += step
    return best_angle


def deskew(gray: Image.Image) -> Image.Image:
    angle = estimate_skew(gray)
    if abs(angle) < 0.25:
        return gray
    return gray.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)


def preprocess_image(img: Image.Image, *, fix_skew: bool = False) -> tuple[Image.Image, float]:
    """캡처/페이지 이미지를 OCR하기 좋게 보정한다. (보정된 이미지, 확대 배율)."""
    gray = to_gray(img)
    gray, scale = upscale(gray)
    if is_dark_background(gray):
        gray = ImageOps.invert(gray)
    gray = remove_shadow(gray)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.MedianFilter(3))  # 잔무늬·배경 장식 줄이기
    if fix_skew:
        gray = deskew(gray)
    return gray, scale


def text_region_ratio(img: Image.Image) -> float:
    """글자가 있을 법한 영역 비율(가로 방향 경계가 촘촘한 부분). 감지 단계에서 쓴다."""
    gray = to_gray(img)
    gray.thumbnail((600, 600))
    a = np.asarray(gray, dtype=np.int16)
    if a.shape[1] < 3:
        return 0.0
    dx = np.abs(np.diff(a, axis=1)) > 40
    rows = dx.sum(axis=1) > max(4, a.shape[1] * 0.02)
    return float(rows.mean())
