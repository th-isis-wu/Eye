"""알림: 자동으로 읽은 공지·자료 중 아직 안 읽은 것을 모아 둔다."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .feedback import data_dir


class Inbox:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "inbox.json"
        self.items: list[dict] = []
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.items = []

    def save(self) -> None:
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, source: str, kind: str, summary: list[str], output: str | None = None) -> dict:
        item = {
            "source": source, "kind": kind, "summary": summary, "output": output,
            "read": False, "at": datetime.now().isoformat(timespec="seconds"),
        }
        self.items = [i for i in self.items if i["source"] != source] + [item]
        self.save()
        return item

    def unread(self) -> list[dict]:
        return [i for i in self.items if not i["read"]]

    def mark_read(self, source: str) -> None:
        for i in self.items:
            if i["source"] == source:
                i["read"] = True
        self.save()
