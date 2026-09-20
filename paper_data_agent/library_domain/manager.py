"""Creation, enumeration, and safe opening of independent paper libraries."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from .models import LibraryInfo
from .repository import PaperLibrary, now_utc, write_json


class LibraryManager:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", name.strip()).strip(" .-")
        return slug[:80] or "论文库"

    def create(self, name: str) -> PaperLibrary:
        base = self._slug(name)
        library_id = base
        counter = 2
        while (self.root / library_id).exists():
            library_id = f"{base}-{counter}"
            counter += 1
        path = self.root / library_id
        path.mkdir()
        now = now_utc()
        write_json(path / "library.json", asdict(LibraryInfo(library_id, name.strip() or base, now, now)))
        write_json(path / "papers.json", [])
        (path / "downloaded_papers").mkdir()
        (path / "sessions").mkdir()
        return PaperLibrary(path)

    def list(self) -> list[LibraryInfo]:
        output: list[LibraryInfo] = []
        for metadata_path in self.root.glob("*/library.json"):
            try:
                output.append(LibraryInfo(**json.loads(metadata_path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(output, key=lambda item: item.updated_at, reverse=True)

    def open(self, library_id: str) -> PaperLibrary:
        path = (self.root / library_id).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("非法论文库路径") from exc
        if not (path / "library.json").is_file():
            raise ValueError(f"论文库不存在：{library_id}")
        return PaperLibrary(path)
