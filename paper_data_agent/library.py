from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from .core import PaperIndex
from .web_sources import download_public_paper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass(slots=True)
class LibraryInfo:
    library_id: str
    name: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class PaperRecord:
    paper_id: str
    title: str
    local_path: str
    source_type: str
    source: str
    resolved_url: str
    sha256: str
    added_at: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str = ""
    cited_by_count: int | None = None


@dataclass(slots=True)
class ImportResult:
    added: int
    duplicates: int
    failed: int
    failures: list[str]


@dataclass(slots=True)
class SearchImportResult:
    query: str
    candidates: int
    downloadable: int
    added: int
    duplicates: int
    failed: int
    imported_titles: list[str]
    failures: list[str]
    year_from: int | None = None
    requested: int = 0
    imported_details: list[dict[str, object]] = field(default_factory=list)

    def as_markdown(self) -> str:
        target = self.requested or self.added
        lines = [
            "# 在线检索并导入结果", "",
            f"查询词：{self.query}",
            (f"年份范围：{self.year_from} 年至今。" if self.year_from else "年份范围：未限制。"),
            f"目标导入 {target} 篇；已成功加入 {self.added} 篇。",
            f"共检索并排序 {self.candidates} 篇候选，优先尝试主题相关且引用较高的公开全文。",
        ]
        if self.imported_details:
            def cell(value: object) -> str:
                return str(value if value not in (None, "") else "—").replace("|", r"\|").replace("\n", " ")
            lines.extend([
                "", "已加入当前论文库：", "",
                "| 论文 | 作者 | 年份 | DOI | OpenAlex 被引次数（检索时） | 公开全文来源 |",
                "|---|---|---:|---|---:|---|",
            ])
            for item in self.imported_details:
                authors = item.get("authors") or []
                if isinstance(authors, list):
                    author_text = "、".join(str(name) for name in authors[:6])
                    if len(authors) > 6:
                        author_text += " 等"
                else:
                    author_text = str(authors)
                lines.append("| " + " | ".join(cell(value) for value in (
                    item.get("title"), author_text, item.get("year"), item.get("doi"),
                    item.get("cited_by_count"), item.get("public_url"),
                )) + " |")
        elif self.imported_titles:
            lines.extend(["", "已加入当前论文库：", *[f"- {title}" for title in self.imported_titles]])
        if self.added < target:
            lines.extend(["", f"还差 {target - self.added} 篇。关键原因："])
            if self.failures:
                lines.extend(f"- {item}" for item in self.failures[:5])
            else:
                lines.append("- 当前候选中没有更多可成功读取的公开全文。")
        return "\n".join(lines)


class PaperLibrary:
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
        _write_json(self.papers_path, [asdict(item) for item in records])
        self.info.updated_at = _now()
        _write_json(self.path / "library.json", asdict(self.info))

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
                digest = _sha256_file(resolved)
                if digest in known_hashes:
                    duplicates += 1
                    continue
                pending.append(
                    PaperRecord(
                        paper_id=uuid.uuid4().hex,
                        title=resolved.stem,
                        local_path=str(resolved),
                        source_type="local",
                        source=str(folder),
                        resolved_url="",
                        sha256=digest,
                        added_at=_now(),
                    )
                )
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
            added_at=_now(),
            authors=[str(name) for name in (authors or []) if str(name).strip()],
            year=year,
            doi=doi,
            cited_by_count=cited_by_count,
        )
        try:
            index = self._build_index_for(records + [record])
        except ValueError as exc:
            return ImportResult(0, 0, 1, [str(exc)])
        if str(downloaded.path.resolve()).lower() not in {
            str(Path(chunk.path).resolve()).lower() for chunk in index.chunks
        }:
            return ImportResult(0, 0, 1, ["下载成功，但 PDF 中没有可提取文本"])
        self._save_records(records + [record])
        index.save(self.index_path)
        return ImportResult(1, 0, 0, [])

    def search_and_import(
        self, query: str, top_k: int = 5, queries: list[str] | None = None,
        year_from: int | None = None,
    ) -> SearchImportResult:
        """Search OpenAlex and import accessible PDFs into this library."""
        from .adapters import ResearchToolAdapters
        target = min(max(int(top_k), 1), 10)
        candidate_target = min(max(target * 4, 20), 40)
        raw_queries = [*(queries or []), query]
        cleaned_queries = []
        for value in raw_queries:
            value = re.sub(r"(?i)\bopen\s+access\b", "", str(value))
            value = re.sub(r"\s+", " ", value).strip()
            if value and value.lower() not in {item.lower() for item in cleaned_queries}:
                cleaned_queries.append(value)
        cleaned_queries = cleaned_queries[:4]
        primary = cleaned_queries[-1] if cleaned_queries else query
        search = ResearchToolAdapters(self.path / "outputs").online_search(
            primary, top_k=candidate_target, queries=cleaned_queries[:-1], year_from=year_from)
        candidates = search.data if isinstance(search.data, list) else []
        stop = {"open", "access", "review", "paper", "model", "models", "study", "analysis",
                "computational", "biology", "related", "latest", "recent", "simulation"}
        term_sets = []
        for value in cleaned_queries:
            terms = {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 2 and term not in stop}
            if terms:
                term_sets.append(terms)
        ranked = []
        for paper in candidates:
            haystack = (str(paper.get("title") or "") + " " + str(paper.get("abstract") or "")).lower()
            tokens = set(re.findall(r"[a-z0-9]+", haystack))
            scores = [len(terms & tokens) / len(terms) for terms in term_sets]
            score = max(scores, default=1.0)
            title_lower = str(paper.get("title") or "").lower()
            phrase_bonus = int(any(value in title_lower for value in ("virtual cell", "whole-cell", "whole cell")))
            if term_sets and score < .5 and not phrase_bonus:
                continue
            ranked.append((phrase_bonus, score, int(paper.get("cited_by_count") or 0), int("review" in title_lower), paper))
        ranked.sort(key=lambda row: row[:4], reverse=True)
        papers = [row[-1] for row in ranked[:candidate_target]]
        added = duplicates = failed = downloadable = 0
        titles: list[str] = []
        imported_details: list[dict[str, object]] = []
        failures: list[str] = []
        for paper in papers:
            if added >= target:
                break
            urls = []
            for value in [paper.get("open_access_url"), *(paper.get("open_access_urls") or [])]:
                value = str(value or "").strip()
                if value and value not in urls:
                    urls.append(value)
            expanded = []
            for url in urls:
                # OpenAlex occasionally exposes Nature's references-only PDF.
                # Try the article PDF first, while retaining the original URL.
                if "nature.com/articles/" in url and url.endswith("_reference.pdf"):
                    expanded.append(url.removesuffix("_reference.pdf") + ".pdf")
                match = re.search(r"cell\.com/action/showPdf\?pii=([A-Za-z0-9]+)", url)
                if match:
                    expanded.append(f"https://www.cell.com/cell/pdf/{match.group(1)}.pdf")
                arxiv = re.search(r"arxiv\.org/abs/([^?#]+)", url, re.I)
                if arxiv:
                    expanded.append(f"https://arxiv.org/pdf/{arxiv.group(1)}")
                pmc = re.search(r"pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)", url, re.I)
                if pmc:
                    expanded.append(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc.group(1).upper()}/")
                expanded.append(url)
            urls = list(dict.fromkeys(expanded))
            def url_priority(value: str) -> tuple[int, int]:
                lower = value.lower()
                repository = any(host in lower for host in (
                    "arxiv.org", "pmc.ncbi.nlm.nih.gov", "europepmc.org",
                    "biorxiv.org", "medrxiv.org", "zenodo.org", "repository", "hal.science"))
                direct_pdf = lower.endswith(".pdf") or "/pdf/" in lower or "showpdf" in lower
                landing = "doi.org/" in lower or "pubmed.ncbi.nlm.nih.gov" in lower
                return (int(repository) * 4 + int(direct_pdf) * 2 - int(landing) * 3, -len(value))
            urls.sort(key=url_priority, reverse=True)
            title = str(paper.get("title") or "未命名论文")
            if not urls:
                failures.append(f"《{title}》：OpenAlex 未提供公开地址")
                continue
            downloadable += 1
            errors = []
            imported = False
            attempted: list[str] = []
            for url in urls[:5]:
                attempted.append(url)
                try:
                    raw_authors = paper.get("authors") or []
                    authors = [str(name) for name in raw_authors] if isinstance(raw_authors, list) else [str(raw_authors)]
                    raw_doi = str(paper.get("doi") or "")
                    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw_doi, flags=re.I)
                    raw_year = paper.get("year")
                    year = int(raw_year) if str(raw_year or "").isdigit() else None
                    raw_citations = paper.get("cited_by_count")
                    citations = int(raw_citations) if str(raw_citations or "").isdigit() else None
                    result = self.import_url(
                        url, title_override=title, authors=authors, year=year,
                        doi=doi, cited_by_count=citations,
                    )
                    added += result.added
                    duplicates += result.duplicates
                    if result.added:
                        titles.append(title)
                        imported_details.append({
                            "title": title, "authors": authors, "year": year, "doi": doi,
                            "cited_by_count": citations, "public_url": url,
                        })
                    if result.added or result.duplicates:
                        imported = True
                        break
                    errors.extend(result.failures)
                except Exception as exc:
                    errors.append(str(exc))
            if not imported:
                failed += 1
                hosts = []
                for attempted_url in attempted:
                    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", attempted_url).split("/", 1)[0])
                    if host and host not in hosts:
                        hosts.append(host)
                reason = errors[-1] if errors else "所有公开地址均无法导入"
                failures.append(f"《{title}》：尝试 {', '.join(hosts) or '公开地址'}；{reason}")
        return SearchImportResult("；".join(cleaned_queries), len(papers), downloadable,
                                  added, duplicates, failed, titles, failures, year_from, target,
                                  imported_details)

    def remove_paper(self, paper_id: str) -> PaperRecord:
        """Remove one record and rebuild the index without deleting its PDF file."""
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
        return removed

    def rebuild_index(self) -> None:
        records = self.records()
        paths = [Path(item.local_path) for item in records if Path(item.local_path).is_file()]
        if not paths:
            return
        self._build_index_for(records).save(self.index_path)

    def paper_count(self) -> int:
        return len(self.records())

    def clear_chat_session(self) -> list[Path]:
        """Archive the active chat/checkpoint without touching papers or outputs."""
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
        now = _now()
        _write_json(path / "library.json", asdict(LibraryInfo(library_id, name.strip() or base, now, now)))
        _write_json(path / "papers.json", [])
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
