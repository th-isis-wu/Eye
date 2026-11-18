"""사용자 피드백: 사용자가 고른 날짜, 고친 글자를 기록해 정보 추출과 검증 규칙을 고친다."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Word

DEFAULT_THRESHOLD = 60.0
MIN_THRESHOLD, MAX_THRESHOLD = 40.0, 80.0


def data_dir() -> Path:
    d = Path(os.environ.get("EYE_HOME", Path.home() / ".eye"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class Feedback:
    """~/.eye/feedback.json 에 저장되는 학습 기록."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "feedback.json"
        self.data: dict[str, Any] = {
            "date_order": {"MD": 0, "DM": 0},  # 두 가지로 읽히는 날짜에서 사용자가 고른 순서
            "corrections": {},  # OCR 결과 → 사용자가 고친 글자
            "flag_stats": {"confirmed": 0, "corrected": 0},  # 불확실 표시가 맞았는지
            "history": [],
        }
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.data.update(saved)
            except (OSError, json.JSONDecodeError):
                pass

    # ------------------------------------------------------------ 규칙
    @property
    def date_preference(self) -> str:
        o = self.data["date_order"]
        dm, md = o.get("DM", 0), o.get("MD", 0)
        return "DM" if dm >= 2 and dm > md else "MD"  # 한 번 고른 것만으로는 바꾸지 않는다

    @property
    def conf_threshold(self) -> float:
        """불확실 표시를 했는데 대부분 맞았다면 기준을 낮추고, 고쳐야 했다면 높인다."""
        s = self.data["flag_stats"]
        c, k = s.get("confirmed", 0), s.get("corrected", 0)
        total = c + k
        if total < 5:
            return DEFAULT_THRESHOLD
        corrected_ratio = k / total
        t = DEFAULT_THRESHOLD + (corrected_ratio - 0.5) * 40
        return max(MIN_THRESHOLD, min(MAX_THRESHOLD, t))

    def apply_corrections(self, words: list[Word]) -> int:
        """예전에 고친 글자를 OCR 결과에 바로 반영한다. 고친 단어는 확신도를 올린다."""
        fixes: dict[str, str] = self.data["corrections"]
        n = 0
        for w in words:
            if w.text in fixes:
                w.text = fixes[w.text]
                w.conf = max(w.conf, 95.0)
                n += 1
        return n

    # ------------------------------------------------------------ 기록
    def record_date_choice(self, raw: str, order: str, chosen_iso: str) -> None:
        self.data["date_order"][order] = self.data["date_order"].get(order, 0) + 1
        self._log({"type": "date", "raw": raw, "order": order, "chosen": chosen_iso})

    def record_word(self, original: str, fixed: str) -> None:
        stats = self.data["flag_stats"]
        if fixed and fixed != original:
            self.data["corrections"][original] = fixed
            stats["corrected"] = stats.get("corrected", 0) + 1
            self._log({"type": "correction", "from": original, "to": fixed})
        else:
            stats["confirmed"] = stats.get("confirmed", 0) + 1
            self._log({"type": "confirm", "text": original})

    def _log(self, entry: dict) -> None:
        entry["at"] = datetime.now().isoformat(timespec="seconds")
        self.data["history"] = (self.data["history"] + [entry])[-500:]
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self.__init__(self.path)
