"""Paper evidence tools and the compatibility tool registry."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ..adapters import ResearchToolAdapters
from ..reading import abstract_or_front_pages, build_documents, estimate_tokens, full_page_unit, select_with_budget
from ..retrieval.index import PaperIndex


class ToolRegistry:
    """Minimal tool registry with required-parameter validation."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[Callable[..., Any], set[str]]] = {}

    def register(self, name: str, function: Callable[..., Any], required: set[str]) -> None:
        if not name or name in self._tools:
            raise ValueError(f"invalid or duplicate tool name: {name}")
        self._tools[name] = (function, required)

    def call(self, name: str, **arguments: Any) -> Any:
        if name not in self._tools:
            raise ValueError(f"unknown tool: {name}")
        function, required = self._tools[name]
        missing = sorted(required - arguments.keys())
        if missing:
            raise ValueError(f"missing required parameters for {name}: {', '.join(missing)}")
        return function(**arguments)


class PaperAgent:
    """Tool-using paper agent that always returns traceable source evidence."""

    def __init__(self, index: PaperIndex, output_dir: Path | None = None, online_importer=None):
        self.index = index
        self.adapters = ResearchToolAdapters(output_dir or (Path.cwd() / "output" / "agent_artifacts"))
        self.tools = ToolRegistry()
        self.tools.register("search_papers", self._search_tool, {"query"})
        self.tools.register("build_brief", self._brief_tool, {"query"})
        self.tools.register("survey_corpus", self._survey_tool, set())
        self.tools.register("read_pages", self._read_pages_tool, {"title", "pages"})
        self.tools.register("read_full_papers", self._read_full_papers_tool, {"titles"})
        self.tools.register("online_search", self._online_search_tool, {"query"})
        if online_importer is not None:
            self.tools.register("search_and_import", online_importer, {"query"})
        self.tools.register("create_scientific_figure", self._figure_tool, {"data_path"})
        self.tools.register("create_presentation", self._presentation_tool, {"spec"})
        self.tools.register("create_mindmap", self._mindmap_tool, set())

    def _online_search_tool(
        self,
        query: str,
        top_k: int = 8,
        queries: list[str] | None = None,
    ) -> str:
        return self.adapters.online_search(
            query=query,
            top_k=top_k,
            queries=queries,
        ).as_markdown()

    def _figure_tool(
        self,
        data_path: str,
        title: str = "Scientific figure",
        chart_type: str = "auto",
        x_column: str = "",
        y_columns: list[str] | None = None,
    ) -> str:
        return self.adapters.create_scientific_figure(
            data_path=data_path,
            title=title,
            chart_type=chart_type,
            x_column=x_column,
            y_columns=y_columns,
        ).as_markdown()

    def _presentation_tool(self, spec: dict[str, Any]) -> str:
        return self.adapters.create_presentation(spec).as_markdown()

    def _mindmap_tool(
        self,
        markdown: str = "",
        markdown_path: str = "",
        title: str = "论文思维导图",
        theme: str = "air",
    ) -> str:
        return self.adapters.create_mindmap(
            markdown=markdown,
            markdown_path=markdown_path,
            title=title,
            theme=theme,
        ).as_markdown()

    def _search_tool(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        return [asdict(hit) for hit in self.index.search(query=query, top_k=top_k)]

    def _read_pages_tool(self, title: str, pages: list[int]) -> str:
        if not isinstance(pages, list) or not pages or len(pages) > 12:
            raise ValueError("每次补读需要 1–12 个 PDF 页码")
        if any(type(page) is not int or page < 1 for page in pages):
            raise ValueError("页码必须是正整数")
        documents = build_documents(self.index.chunks)
        matches = [item for item in documents if item.title == title]
        if len(matches) != 1:
            raise ValueError("请使用证据清单中的精确论文标题；当前标题不存在或不唯一")
        document = matches[0]
        lines = [f"# 补读：{title}", f"来源：{document.path}", "范围：指定 PDF 页的完整提取文本；未读取其他页。"]
        for page in sorted(set(pages)):
            if page not in document.pages:
                lines.append(f"## PDF 第 {page} 页\n当前索引没有该页文本，未读取。")
            else:
                lines.append(f"## PDF 第 {page} 页\n{document.pages[page]}")
        return "\n\n".join(lines)

    def _read_full_papers_tool(
        self,
        titles: list[str],
        evidence_token_budget: int = 80_000,
    ) -> str:
        """Read complete indexed text for a small, explicitly selected paper set.

        A paper is either included in full or omitted. The tool never silently
        substitutes an abstract or a partial prefix for a requested full text.
        """
        if not isinstance(titles, list) or not titles or len(titles) > 5:
            raise ValueError("每次全文阅读需要提供 1–5 个精确论文标题")
        if any(not isinstance(title, str) or not title.strip() for title in titles):
            raise ValueError("全文阅读的论文标题不能为空")
        try:
            budget = int(evidence_token_budget)
        except (TypeError, ValueError) as exc:
            raise ValueError("全文阅读预算必须是正整数") from exc
        if budget < 1 or budget > 120_000:
            raise ValueError("单次全文阅读预算需要在 1–120000 token 之间")

        documents = build_documents(self.index.chunks)
        by_title = {document.title: document for document in documents}
        unique_titles = list(dict.fromkeys(titles))
        missing = [title for title in unique_titles if title not in by_title]
        if missing:
            raise ValueError("请使用证据清单中的精确论文标题；未找到：" + "；".join(missing))

        selected = []
        skipped = []
        used_tokens = 0
        for title in unique_titles:
            document = by_title[title]
            page_numbers = tuple(sorted(document.pages))
            text = "\n\n".join(
                f"[PDF page {page}]\n{document.pages[page]}" for page in page_numbers
            )
            tokens = estimate_tokens(text)
            item = (document, page_numbers, text, tokens)
            if used_tokens + tokens <= budget:
                selected.append(item)
                used_tokens += tokens
            else:
                skipped.append(item)

        selected_ids = {item[0].paper_id for item in selected}
        lines = [
            "# 按篇全文阅读记录",
            "",
            f"- 请求：{len(unique_titles)} 篇；完整读取：{len(selected)} 篇；因本轮预算未读：{len(skipped)} 篇。",
            f"- 本轮全文证据预算：约 {budget} token；实际使用：约 {used_tokens} token。",
            "- 完整的含义：读取当前本地 PDF 索引中该文件所有具有可提取文本的页面；图片、扫描页或公式的视觉信息不自动等同于已读。",
            "",
            "| 论文 | PDF 文本页数 | 状态 | 估算 token |",
            "|---|---:|---|---:|",
        ]
        for document, pages, _text, tokens in [*selected, *skipped]:
            status = "全文已读" if document.paper_id in selected_ids else "预算不足，本轮未读"
            lines.append(f"| {document.title} | {len(pages)} | {status} | {tokens} |")
        lines.extend(["", "## 完整全文证据", ""])
        for position, (document, pages, text, tokens) in enumerate(selected, start=1):
            lines.extend(
                [
                    f"### {position}. {document.title}",
                    f"- Source: `{document.path}`",
                    *([f"- Original URL: {document.source_url}"] if document.source_url else []),
                    f"- Read scope: all {len(pages)} indexed text pages; estimated {tokens} token",
                    "",
                    text,
                    "",
                ]
            )
        if skipped:
            lines.extend(
                [
                    "## 未覆盖声明",
                    "",
                    "预算不足的论文没有被部分塞入证据。需要继续时，应分下一批完整读取。",
                ]
            )
        return "\n".join(lines)

    def _brief_tool(
        self,
        query: str,
        top_k: int = 5,
        evidence_token_budget: int = 30_000,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        # Retrieve extra chunks first, then keep the best page from each paper.
        # This makes "top_k" mean papers rather than accidentally counting several
        # matching chunks from the same PDF as separate papers.
        raw_hits = self.index.search(query=query, top_k=max(top_k * 4, top_k))
        lines = [f"# Focused reading packet: {query}", ""]
        if not raw_hits:
            lines.append("没有找到匹配证据；未阅读任何论文页面。")
            return "\n".join(lines)
        documents = {item.paper_id: item for item in build_documents(self.index.chunks)}
        paper_ids_by_path = {
            str(Path(chunk.path).resolve()).lower(): chunk.paper_id for chunk in self.index.chunks
        }
        candidates = []
        seen_papers: set[str] = set()
        for hit in raw_hits:
            paper_id = paper_ids_by_path.get(str(Path(hit.path).resolve()).lower(), "")
            if not paper_id or paper_id in seen_papers:
                continue
            document = documents.get(paper_id)
            if document:
                seen_papers.add(paper_id)
                candidates.append(
                    full_page_unit(
                        document,
                        hit.page,
                        f"{('BM25+向量混合检索' if hit.retrieval == 'hybrid' else 'BM25 检索')}命中该页（score={hit.score}）；读取整页，不截取命中句前后固定字符。",
                    )
                )
            if len(candidates) >= top_k:
                break
        if progress_callback:
            total = max(len(candidates), 1)
            for current in range(1, len(candidates) + 1):
                progress_callback(current, total)
        selected, skipped, used_tokens = select_with_budget(candidates, evidence_token_budget)
        lines.extend(
            [
                "## 阅读计划与覆盖",
                "",
                f"- 候选论文：{len(candidates)} 篇；实际完整读取：{len(selected)} 篇；因预算跳过：{len(skipped)} 篇。",
                f"- 证据预算：约 {evidence_token_budget} token；本次完整页面估算使用：约 {used_tokens} token。",
                "- 阅读策略：先用可用的 BM25/向量混合检索选择最相关论文页面，再读取命中页的完整提取文本。未建立向量索引时自动回退 BM25；没有使用 420/520 字符截断。",
                "",
                "| 论文 | 阅读范围 | 完整性 | 选择原因 |",
                "|---|---|---|---|",
            ]
        )
        for unit in [*selected, *skipped]:
            status = "已读完整页" if unit in selected else "预算不足，未读"
            lines.append(f"| {unit.title} | PDF 第 {unit.pages[0]} 页 | {status} | {unit.reason} |")
        lines.extend(["", "## 完整页面证据", ""])
        for position, unit in enumerate(selected, start=1):
            lines.extend(
                [
                    f"### {position}. {unit.title}",
                    "",
                    f"- Source: `{unit.path}`",
                    *([f"- Original URL: {unit.source_url}"] if unit.source_url else []),
                    f"- Page: {unit.pages[0]}",
                    f"- 阅读单元：完整 PDF 页面；估算 {unit.estimated_tokens} token",
                    f"- 选择原因：{unit.reason}",
                    "",
                    unit.text,
                    "",
                ]
            )
        lines.extend(
            [
                "## 使用边界",
                "",
                "这里只能支持所列完整页面中的内容。未读取的章节不能写成‘论文没有讨论’，只能写成‘本次阅读范围内未看到’。",
            ]
        )
        return "\n".join(lines)

    def _survey_tool(
        self,
        evidence_token_budget: int = 80_000,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        """Plan and execute complete per-paper reading units for corpus questions."""
        documents = build_documents(self.index.chunks)
        candidates = []
        for current, document in enumerate(documents, start=1):
            candidates.append(abstract_or_front_pages(document))
            if progress_callback:
                progress_callback(current, len(documents))
        selected, skipped, used_tokens = select_with_budget(candidates, evidence_token_budget)
        abstract_count = sum(unit.unit == "complete_abstract" for unit in selected)
        page_fallback_count = sum(unit.unit == "complete_front_pages" for unit in selected)
        lines = [
            "# Corpus reading plan and evidence",
            "",
            f"Included papers: {len(selected)} of {len(documents)}",
            "",
            "## 阅读计划与覆盖",
            "",
            f"- 论文库总数：{len(documents)} 篇；实际读取：{len(selected)} 篇；预算不足未读：{len(skipped)} 篇。",
            f"- 证据预算：约 {evidence_token_budget} token；本次读取内容估算使用：约 {used_tokens} token。",
            f"- 完整摘要：{abstract_count} 篇；无法可靠识别摘要边界而改读完整首页/前两页：{page_fallback_count} 篇。",
            "- 原则：只使用完整阅读单元；不再把每篇首 chunk 的前 520 字符称为摘要。",
            "",
            "| # | 论文 | 实际阅读范围 | 阅读单元 | 估算 token | 选择说明 |",
            "|---|---|---|---|---|---|",
        ]
        for number, unit in enumerate([*selected, *skipped], start=1):
            page_text = ", ".join(str(page) for page in unit.pages) or "-"
            unit_name = "完整摘要" if unit.unit == "complete_abstract" else "完整首页/前两页"
            if unit in skipped:
                unit_name = "预算不足，未读"
            lines.append(
                f"| {number} | {unit.title} | PDF 页 {page_text} | {unit_name} | {unit.estimated_tokens} | {unit.reason} |"
            )
        lines.extend(
            [
                "",
                "## 已读取证据",
                "",
            ]
        )
        for number, unit in enumerate(selected, start=1):
            page_text = ", ".join(str(page) for page in unit.pages)
            unit_name = "完整摘要" if unit.unit == "complete_abstract" else "完整首页/前两页"
            lines.extend(
                [
                    f"## {number}. {unit.title}",
                    f"Source: {unit.path}",
                    *([f"Original URL: {unit.source_url}"] if unit.source_url else []),
                    f"Read scope: {unit_name}; PDF page(s): {page_text}; estimated tokens: {unit.estimated_tokens}",
                    f"Why this scope: {unit.reason}",
                    "",
                    unit.text,
                    "",
                ]
            )
        if skipped:
            lines.extend(
                [
                    "## 未覆盖声明",
                    "",
                    "以上跳过论文未进入证据，最终回答不得把结果称为完整全库结论。",
                    "",
                ]
            )
        lines.extend(
            [
                "## 回答约束",
                "",
                "回答开头必须用简明中文报告实际覆盖数与阅读范围。不要反复说‘被截断’；如果某篇没有识别出完整摘要，应明确说已改读哪几个完整页面。",
            ]
        )
        return "\n".join(lines)

    def run(self, action: str, **arguments: Any) -> Any:
        return self.tools.call(action, **arguments)
