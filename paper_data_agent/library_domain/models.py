"""Serializable records shared by paper library services and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field


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
