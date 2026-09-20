"""Single-library persistence, local import, indexing, and session operations."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from ..embeddings import DEFAULT_EMBEDDING_MODEL, vector_paths, vector_status
from ..retrieval.index import PaperIndex
from ..web_sources import download_public_paper
from .models import ImportResult, LibraryInfo, PaperRecord
from .online_import import OnlineImportMixin


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PaperLibrary(OnlineImportMixin):
    def __init__(self, path: Path):
        self.path = path.resolve()
        metadata = json.loads((self.path / "library.json").read_text(encoding="utf-8"))
        self.info = LibraryInfo(**metadata)
        self.papers_path = self.path / "papers.json"
        self.index_path = self.path / "index.json"
        self.downloads_path = self.path / "downloaded_papers"
        self.sessions_path = self.path / "sessions"
        self.downloads_path.mkdir(exist_ok=True)
        self.sessions_path.mkdir(exist_ok=True)

    def records(self) -> list[PaperRecord]:
        if not self.papers_path.is_file():
            return []
        return [PaperRecord(**item) for item in json.loads(self.papers_path.read_text(encoding="utf-8"))]

    def _save_records(self, records: list[PaperRecord]) -> None:
        write_json(self.papers_path, [asdict(item) for item in records])
        self.info.updated_at = now_utc()
        write_json(self.path / "library.json", asdict(self.info))

    @staticmethod
    def _build_index_for(records: list[PaperRecord]) -> PaperIndex:
        paths = [Path(item.local_path) for item in records if Path(item.local_path).is_file()]
        index = PaperIndex.build_from_paths(paths)
        records_by_path = {
            str(Path(item.local_path).resolve()).lower(): item
            for item in records
        }
        urls = {
            str(Path(item.local_path).resolve()).lower(): item.resolved_url or item.source
            for item in records
            if item.source_type == "web"
        }
        for chunk in index.chunks:
            key = str(Path(chunk.path).resolve()).lower()
            record = records_by_path.get(key)
            if record:
                chunk.paper_id = record.paper_id
                chunk.title = record.title
            chunk.source_url = urls.get(key, "")
        return index

    def import_folder(self, folder: Path) -> ImportResult:
        folder = folder.expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"文件夹不存在：{folder}")
        candidates = sorted(folder.rglob("*.pdf"), key=lambda item: str(item).lower())
        records = self.records()
        known_hashes = {item.sha256 for item in records}
        known_paths = {str(Path(item.local_path)).lower() for item in records}
        duplicates = failed = 0
        failures: list[str] = []
        pending: list[PaperRecord] = []
        for path in candidates:
            try:
                resolved = path.resolve()
                if str(resolved).lower() in known_paths:
                    duplicates += 1
                    continue
                digest = sha256_file(resolved)
                if digest in known_hashes:
                    duplicates += 1
                    continue
                pending.append(PaperRecord(
                    paper_id=uuid.uuid4().hex,
                    title=resolved.stem,
                    local_path=str(resolved),
                    source_type="local",
                    source=str(folder),
                    resolved_url="",
                    sha256=digest,
                    added_at=now_utc(),
                ))
                known_hashes.add(digest)
                known_paths.add(str(resolved).lower())
            except OSError as exc:
                failed += 1
                failures.append(f"{path}: {exc}")
        if not pending:
            return ImportResult(0, duplicates, failed, failures)
        try:
            index = self._build_index_for(records + pending)
        except ValueError as exc:
            return ImportResult(0, duplicates, failed + len(pending), failures + [str(exc)])
        indexed_paths = {str(Path(chunk.path).resolve()).lower() for chunk in index.chunks}
        valid_pending = [item for item in pending if str(Path(item.local_path).resolve()).lower() in indexed_paths]
        invalid_pending = [item for item in pending if item not in valid_pending]
        for item in invalid_pending:
            failures.append(f"无法提取 PDF 文本：{item.local_path}")
        self._save_records(records + valid_pending)
        index.save(self.index_path)
        return ImportResult(len(valid_pending), duplicates, failed + len(invalid_pending), failures)

    def import_url(
        self, url: str, allow_private: bool = False, title_override: str = "",
        authors: list[str] | None = None, year: int | None = None,
        doi: str = "", cited_by_count: int | None = None,
    ) -> ImportResult:
        downloaded = download_public_paper(url, self.downloads_path, allow_private=allow_private)
        records = self.records()
        if downloaded.sha256 in {item.sha256 for item in records}:
            return ImportResult(0, 1, 0, [])
        record = PaperRecord(
            paper_id=uuid.uuid4().hex,
            title=title_override.strip() or downloaded.title,
            local_path=str(downloaded.path),
            source_type="web",
            source=downloaded.source_url,
            resolved_url=downloaded.resolved_url,
            sha256=downloaded.sha256,
            added_at=now_utc(),
            authors=[str(name) for name in (authors or []) if str(name).strip()],
            year=year,
            doi=doi,
            cited_by_count=cited_by_count,
        )
        try:
            index = self._build_index_for(records + [record])
        except ValueError as exc:
            return ImportResult(0, 0, 1, [str(exc)])
        indexed_paths = {str(Path(chunk.path).resolve()).lower() for chunk in index.chunks}
        if str(downloaded.path.resolve()).lower() not in indexed_paths:
            return ImportResult(0, 0, 1, ["下载成功，但 PDF 中没有可提取文本"])
        self._save_records(records + [record])
        index.save(self.index_path)
        return ImportResult(1, 0, 0, [])

    def remove_paper(self, paper_id: str) -> PaperRecord:
        records = self.records()
        removed = next((item for item in records if item.paper_id == paper_id), None)
        if removed is None:
            raise ValueError("没有找到要移除的论文")
        remaining = [item for item in records if item.paper_id != paper_id]
        index = self._build_index_for(remaining) if remaining else None
        self._save_records(remaining)
        if index is not None:
            index.save(self.index_path)
        elif self.index_path.exists():
            self.index_path.unlink()
            for sidecar in vector_paths(self.index_path):
                if sidecar.exists():
                    sidecar.unlink()
        return removed

    def rebuild_index(self) -> None:
        records = self.records()
        paths = [Path(item.local_path) for item in records if Path(item.local_path).is_file()]
        if paths:
            self._build_index_for(records).save(self.index_path)

    def build_vector_index(
        self, model_name: str = DEFAULT_EMBEDDING_MODEL, batch_size: int = 24,
    ) -> dict[str, object]:
        if not self.index_path.is_file():
            raise ValueError("当前论文库还没有全文索引，请先导入论文")
        index = PaperIndex.load(self.index_path)
        embedding = index.build_embeddings(self.index_path, model_name=model_name, batch_size=batch_size)
        return {
            "model": embedding.model_name,
            "chunks": len(index.chunks),
            "dimensions": int(embedding.vectors.shape[1]),
            "status": "可用",
        }

    def vector_index_status(self) -> str:
        if not self.index_path.is_file():
            return "未建立"
        try:
            index = PaperIndex.load(self.index_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return "需要更新"
        if index.embedding_index is not None:
            return "可用"
        vectors_path, metadata_path = vector_paths(self.index_path)
        if vectors_path.exists() or metadata_path.exists():
            return "需要更新"
        return vector_status(self.index_path, index.chunks)

    def paper_count(self) -> int:
        return len(self.records())

    def clear_chat_session(self) -> list[Path]:
        archived: list[Path] = []
        archive_dir = self.sessions_path / "archive"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        for name in ("latest.json", "in_progress.json"):
            source = self.sessions_path / name
            if not source.is_file():
                continue
            archive_dir.mkdir(exist_ok=True)
            target = archive_dir / f"{source.stem}-{timestamp}{source.suffix}"
            source.replace(target)
            archived.append(target)
        return archived
