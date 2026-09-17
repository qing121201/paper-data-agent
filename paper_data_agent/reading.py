from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import PaperChunk


@dataclass(frozen=True, slots=True)
class PaperDocument:
    paper_id: str
    title: str
    path: str
    source_url: str
    pages: dict[int, str]


@dataclass(frozen=True, slots=True)
class ReadingUnit:
    paper_id: str
    title: str
    path: str
    source_url: str
    unit: str
    pages: tuple[int, ...]
    text: str
    complete: bool
    reason: str
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    ascii_count = sum(1 for char in text if ord(char) < 128)
    other_count = len(text) - ascii_count
    return max(1, math.ceil(ascii_count / 4 + other_count))


def _merge_overlapping(parts: list[str]) -> str:
    merged = ""
    for part in parts:
        value = " ".join(part.split()).strip()
        if not value:
            continue
        if not merged:
            merged = value
            continue
        overlap = 0
        maximum = min(400, len(merged), len(value))
        for size in range(maximum, 19, -1):
            if merged[-size:] == value[:size]:
                overlap = size
                break
        merged += ("" if overlap else " ") + value[overlap:]
    return merged.strip()


def build_documents(chunks: list[PaperChunk]) -> list[PaperDocument]:
    grouped: dict[str, list[PaperChunk]] = defaultdict(list)
    for chunk in chunks:
        grouped[chunk.paper_id].append(chunk)
    documents: list[PaperDocument] = []
    for paper_id, paper_chunks in grouped.items():
        by_page: dict[int, list[PaperChunk]] = defaultdict(list)
        for chunk in paper_chunks:
            by_page[chunk.page].append(chunk)
        pages = {
            page: _merge_overlapping([item.text for item in sorted(items, key=lambda row: row.chunk_id)])
            for page, items in sorted(by_page.items())
        }
        first = min(paper_chunks, key=lambda row: (row.page, row.chunk_id))
        documents.append(PaperDocument(paper_id, first.title, first.path, first.source_url, pages))
    return sorted(documents, key=lambda item: item.title.lower())


ABSTRACT_START = re.compile(r"\babstract\b\s*[:.\-—]?\s*", re.IGNORECASE)
ABSTRACT_END = re.compile(
    r"\s(?:keywords?|index\s+terms|ccs\s+concepts|categories\s+and\s+subject\s+descriptors)\s*[:.\-—]?"
    r"|\s(?:1\.?|I\.?)\s+(?:introduction|intro)\b",
    re.IGNORECASE,
)


def abstract_or_front_pages(document: PaperDocument, fallback_pages: int = 2) -> ReadingUnit:
    page_numbers = sorted(document.pages)
    inspected = page_numbers[:3]
    for position, page_number in enumerate(inspected):
        page_text = document.pages[page_number]
        start = ABSTRACT_START.search(page_text)
        if not start:
            continue
        pieces = [page_text[start.end() :]]
        used_pages = [page_number]
        for next_page in inspected[position + 1 :]:
            pieces.append(document.pages[next_page])
            used_pages.append(next_page)
        combined = " ".join(piece.strip() for piece in pieces if piece.strip())
        end = ABSTRACT_END.search(combined)
        if end and end.start() >= 80:
            abstract = combined[: end.start()].strip()
            if len(abstract) >= 80:
                # Determine the last page actually contributing to the abstract.
                consumed = 0
                actual_pages: list[int] = []
                for number, piece in zip(used_pages, pieces):
                    consumed += len(piece.strip()) + 1
                    actual_pages.append(number)
                    if consumed >= end.start():
                        break
                return ReadingUnit(
                    document.paper_id,
                    document.title,
                    document.path,
                    document.source_url,
                    "complete_abstract",
                    tuple(actual_pages),
                    abstract,
                    True,
                    "检测到 Abstract 起点及其后的 Introduction/Keywords 边界，完整读取边界内文本。",
                    estimate_tokens(abstract),
                )
        break

    selected_pages = tuple(page_numbers[: max(1, fallback_pages)])
    text = "\n\n".join(
        f"[PDF page {page}]\n{document.pages[page]}" for page in selected_pages
    )
    return ReadingUnit(
        document.paper_id,
        document.title,
        document.path,
        document.source_url,
        "complete_front_pages",
        selected_pages,
        text,
        True,
        "未能可靠识别完整摘要边界，因此不截取所谓‘摘要片段’，改读完整首页/前两页。",
        estimate_tokens(text),
    )


def full_page_unit(document: PaperDocument, page: int, reason: str) -> ReadingUnit:
    text = document.pages.get(page, "").strip()
    return ReadingUnit(
        document.paper_id,
        document.title,
        document.path,
        document.source_url,
        "complete_page",
        (page,),
        text,
        bool(text),
        reason,
        estimate_tokens(text) if text else 0,
    )


def select_with_budget(units: list[ReadingUnit], token_budget: int) -> tuple[list[ReadingUnit], list[ReadingUnit], int]:
    if token_budget < 1:
        raise ValueError("token_budget must be positive")
    selected: list[ReadingUnit] = []
    skipped: list[ReadingUnit] = []
    used = 0
    for unit in units:
        if unit.complete and used + unit.estimated_tokens <= token_budget:
            selected.append(unit)
            used += unit.estimated_tokens
        else:
            skipped.append(unit)
    return selected, skipped, used
