"""Portable paper index, PDF text extraction, BM25, and hybrid retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..embeddings import DEFAULT_EMBEDDING_MODEL, LocalEmbeddingIndex, vector_paths


TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_+.-]*|[\u4e00-\u9fff]")


def _extract_pdf_pages(path: Path) -> list[str]:
    """Extract pages with pypdf when installed, otherwise use PyMuPDF."""
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        try:
            import fitz
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "需要 PDF 解析器：请安装 pypdf，或使用包含 PyMuPDF 的 Python 环境"
            ) from exc
        with fitz.open(path) as document:
            return [page.get_text("text") for page in document]
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def tokenize(text: str) -> list[str]:
    """Tokenize English technical text and Chinese characters without extra models."""
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


@dataclass(slots=True)
class PaperChunk:
    paper_id: str
    title: str
    path: str
    page: int
    chunk_id: int
    text: str
    source_url: str = ""


@dataclass(slots=True)
class SearchHit:
    title: str
    path: str
    page: int
    score: float
    text: str
    source_url: str = ""
    retrieval: str = "bm25"


class PaperIndex:
    """Portable JSON index plus an in-memory BM25 retriever."""

    def __init__(self, chunks: list[PaperChunk]):
        self.chunks = chunks
        self.embedding_index: LocalEmbeddingIndex | None = None
        self._tokens = [tokenize(chunk.text) for chunk in chunks]
        self._term_counts = [Counter(tokens) for tokens in self._tokens]
        self._doc_freq: Counter[str] = Counter()
        for tokens in self._tokens:
            self._doc_freq.update(set(tokens))
        self._avg_length = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens)
            if self._tokens
            else 0.0
        )

    @classmethod
    def build(cls, input_dir: Path, chunk_size: int = 900, overlap: int = 120) -> "PaperIndex":
        if not input_dir.is_dir():
            raise ValueError(f"PDF directory does not exist: {input_dir}")
        return cls.build_from_paths(input_dir.rglob("*.pdf"), chunk_size=chunk_size, overlap=overlap)

    @classmethod
    def build_from_paths(
        cls,
        pdf_paths: Any,
        chunk_size: int = 900,
        overlap: int = 120,
    ) -> "PaperIndex":
        if chunk_size < 200 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("chunk_size must be >= 200 and 0 <= overlap < chunk_size")

        chunks: list[PaperChunk] = []
        paths = sorted(
            {Path(item).resolve() for item in pdf_paths if Path(item).suffix.lower() == ".pdf"},
            key=lambda item: str(item).lower(),
        )
        for pdf_path in paths:
            if not pdf_path.is_file():
                continue
            try:
                pages = _extract_pdf_pages(pdf_path)
            except Exception:
                continue
            digest = hashlib.sha256(str(pdf_path).lower().encode("utf-8")).hexdigest()[:12]
            paper_id = f"{pdf_path.stem.lower()}-{digest}"
            for page_number, page_text in enumerate(pages, start=1):
                try:
                    text = re.sub(r"\s+", " ", page_text or "").strip()
                except Exception:
                    text = ""
                if not text:
                    continue
                start = 0
                local_id = 0
                while start < len(text):
                    end = min(len(text), start + chunk_size)
                    piece = text[start:end].strip()
                    if piece:
                        chunks.append(
                            PaperChunk(
                                paper_id=paper_id,
                                title=pdf_path.stem,
                                path=str(pdf_path.resolve()),
                                page=page_number,
                                chunk_id=local_id,
                                text=piece,
                            )
                        )
                    if end == len(text):
                        break
                    start = end - overlap
                    local_id += 1
        if not chunks:
            raise ValueError("No extractable PDF text found in the selected sources")
        return cls(chunks)

    @classmethod
    def load(cls, path: Path) -> "PaperIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        index = cls([PaperChunk(**item) for item in payload["chunks"]])
        vectors_path, metadata_path = vector_paths(path)
        if vectors_path.is_file() and metadata_path.is_file():
            try:
                index.embedding_index = LocalEmbeddingIndex.load(
                    vectors_path, metadata_path, index.chunks
                )
            except Exception:
                # A stale or damaged vector sidecar must never make the portable
                # BM25 JSON index unusable.
                index.embedding_index = None
        return index

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        papers = sorted({chunk.title for chunk in self.chunks})
        payload = {
            "format": "paper-data-agent-index-v1",
            "paper_count": len(papers),
            "chunk_count": len(self.chunks),
            "papers": papers,
            "chunks": [asdict(chunk) for chunk in self.chunks],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def build_embeddings(
        self,
        index_path: Path,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        encoder: Any | None = None,
        batch_size: int = 24,
    ) -> LocalEmbeddingIndex:
        vectors_path, metadata_path = vector_paths(index_path)
        self.embedding_index = LocalEmbeddingIndex.build(
            self.chunks,
            vectors_path,
            metadata_path,
            model_name=model_name,
            encoder=encoder,
            batch_size=batch_size,
        )
        return self.embedding_index

    def _bm25_score(self, query_tokens: list[str], index: int) -> float:
        if not query_tokens or not self.chunks:
            return 0.0
        k1, b = 1.5, 0.75
        counts = self._term_counts[index]
        length = max(1, len(self._tokens[index]))
        total = len(self.chunks)
        score = 0.0
        for token in set(query_tokens):
            frequency = counts.get(token, 0)
            if frequency == 0:
                continue
            document_frequency = self._doc_freq.get(token, 0)
            inverse_frequency = math.log(1 + (total - document_frequency + 0.5) / (document_frequency + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / max(self._avg_length, 1.0))
            score += inverse_frequency * frequency * (k1 + 1) / denominator
        return score

    def _bm25_ranked(self, query: str) -> list[tuple[float, int]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            raise ValueError("query must contain searchable words")
        return sorted(
            ((self._bm25_score(query_tokens, idx), idx) for idx in range(len(self.chunks))),
            key=lambda item: item[0],
            reverse=True,
        )

    def _hits_from_ranked(
        self, ranked: list[tuple[float, int]], top_k: int, retrieval: str
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        seen_papers: set[str] = set()
        for score, index in ranked:
            chunk = self.chunks[index]
            if score <= 0 or chunk.paper_id in seen_papers:
                continue
            seen_papers.add(chunk.paper_id)
            hits.append(
                SearchHit(
                    title=chunk.title,
                    path=chunk.path,
                    page=chunk.page,
                    score=round(score, 4),
                    text=chunk.text,
                    source_url=chunk.source_url,
                    retrieval=retrieval,
                )
            )
            if len(hits) >= top_k:
                break
        return hits

    def search_bm25(self, query: str, top_k: int = 5) -> list[SearchHit]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        return self._hits_from_ranked(self._bm25_ranked(query), top_k, "bm25")

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        bm25_ranked = self._bm25_ranked(query)
        if self.embedding_index is None:
            return self._hits_from_ranked(bm25_ranked, top_k, "bm25")

        semantic_scores = self.embedding_index.scores(query)
        semantic_ranked = sorted(
            ((float(score), index) for index, score in enumerate(semantic_scores)),
            key=lambda item: item[0],
            reverse=True,
        )
        # Reciprocal-rank fusion compares order rather than incomparable raw
        # BM25 and cosine scales. Limiting each list keeps weak tail matches
        # from overwhelming useful evidence.
        fused: defaultdict[int, float] = defaultdict(float)
        for rank, (score, index) in enumerate(bm25_ranked[:200], start=1):
            if score > 0:
                fused[index] += 1.0 / (60 + rank)
        for rank, (_score, index) in enumerate(semantic_ranked[:200], start=1):
            fused[index] += 1.0 / (60 + rank)
        ranked = sorted(((score, index) for index, score in fused.items()), reverse=True)
        return self._hits_from_ranked(ranked, top_k, "hybrid")

    def filename_baseline(self, query: str, top_k: int = 5) -> list[str]:
        query_tokens = set(tokenize(query))
        titles = sorted({chunk.title for chunk in self.chunks})
        scored = []
        for title in titles:
            title_tokens = set(tokenize(title))
            score = len(query_tokens & title_tokens)
            scored.append((score, title.lower(), title))
        scored.sort(reverse=True)
        return [title for score, _, title in scored if score > 0][:top_k]

    def search_documents(self, query: str, top_k: int = 5) -> list[str]:
        return [hit.title for hit in self.search(query, top_k=top_k)]

    def search_bm25_documents(self, query: str, top_k: int = 5) -> list[str]:
        return [hit.title for hit in self.search_bm25(query, top_k=top_k)]
