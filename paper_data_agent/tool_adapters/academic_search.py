"""OpenAlex academic-search adapter behavior."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlencode

from .common import AdapterResult, PROJECT_ROOT, WINDOWS_NO_WINDOW


class AcademicSearchMixin:
    """Provide controlled multi-query OpenAlex search."""

    def _online_search_one(self, query: str, top_k: int = 8, year_from: int | None = None) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("在线检索需要非空查询词")
        limit = min(max(int(top_k), 1), 40)
        script = PROJECT_ROOT / "third_party" / "nature_skills" / "nature-academic-search" / "scripts" / "academic_search.py"
        command = [sys.executable, str(script), query.strip(), "--limit", str(limit)]
        if year_from:
            command.extend(["--year-from", str(int(year_from))])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if completed.returncode == 0:
            papers = json.loads(completed.stdout)
        else:
            # Some Windows machines have a stale WinINET/Python proxy while
            # curl can still connect directly. Keep this fallback explicit and
            # read-only instead of changing the user's global proxy settings.
            candidate_limit = min(max(limit * 5, 20), 100)
            params = {"search": query.strip(), "per_page": candidate_limit, "mailto": "paper-agent@example.invalid"}
            if year_from:
                params["filter"] = f"from_publication_date:{int(year_from)}-01-01"
            url = "https://api.openalex.org/works?" + urlencode(params)
            fallback = subprocess.run(
                ["curl.exe", "--proxy", "", "--silent", "--show-error", "--max-time", "45", url],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=50,
                check=False,
                creationflags=WINDOWS_NO_WINDOW,
            )
            if fallback.returncode != 0:
                detail = (fallback.stderr or completed.stderr or completed.stdout).strip()[:600]
                raise RuntimeError(f"OpenAlex 在线检索失败：{detail}")
            raw = json.loads(fallback.stdout)
            candidates = []
            query_terms = {
                term for term in re.findall(r"[A-Za-z0-9]+", query.lower())
                if len(term) > 2 and term not in {"paper", "papers", "about", "with", "from"}
            }
            for item in raw.get("results", []):
                authors = [
                    part.get("author", {}).get("display_name", "")
                    for part in item.get("authorships", [])[:12]
                ]
                location = item.get("best_oa_location") or item.get("primary_location") or {}
                public_urls = []
                for candidate_location in [item.get("best_oa_location"), item.get("primary_location"), *(item.get("locations") or [])]:
                    if not isinstance(candidate_location, dict):
                        continue
                    for candidate_url in (candidate_location.get("pdf_url"), candidate_location.get("landing_page_url")):
                        if candidate_url and candidate_url not in public_urls:
                            public_urls.append(candidate_url)
                paper = {
                    "title": item.get("display_name") or item.get("title"),
                    "year": item.get("publication_year"),
                    "publication_date": item.get("publication_date", ""),
                    "doi": item.get("doi"),
                    "authors": [name for name in authors if name],
                    "cited_by_count": item.get("cited_by_count", 0),
                    "journal": ((item.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                    "landing_url": ((item.get("primary_location") or {}).get("landing_page_url")
                                    or (item.get("best_oa_location") or {}).get("landing_page_url")
                                    or item.get("doi") or item.get("id")),
                    "work_type": item.get("type", ""),
                    "is_retracted": bool(item.get("is_retracted")),
                    "open_access_url": location.get("pdf_url") or location.get("landing_page_url"),
                    "open_access_urls": public_urls,
                    "openalex_id": item.get("id"),
                    "abstract": self._reconstruct_openalex_abstract(item),
                    "relevance_score": item.get("relevance_score"),
                }
                title_terms = set(re.findall(r"[A-Za-z0-9]+", str(paper["title"]).lower()))
                overlap = len(query_terms & title_terms)
                candidates.append((overlap, int(paper["cited_by_count"] or 0), paper))
            candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
            papers = [paper for _overlap, _citations, paper in candidates[:limit]]
        if not isinstance(papers, list):
            raise RuntimeError("OpenAlex 返回格式异常")
        return papers

    @staticmethod
    def _reconstruct_openalex_abstract(item: dict[str, Any]) -> str:
        inverted = item.get("abstract_inverted_index")
        if not isinstance(inverted, dict):
            return ""
        positions: list[tuple[int, str]] = []
        for word, indexes in inverted.items():
            if isinstance(indexes, list):
                positions.extend((int(index), str(word)) for index in indexes)
        positions.sort()
        return " ".join(word for _index, word in positions)

    def online_search(
        self,
        query: str,
        top_k: int = 8,
        queries: list[str] | None = None,
        year_from: int | None = None,
    ) -> AdapterResult:
        query_list: list[str] = []
        for item in [*(queries or []), query]:
            value = str(item).strip()
            if value and value.lower() not in {existing.lower() for existing in query_list}:
                query_list.append(value)
        query_list = query_list[:4]
        if not query_list:
            raise ValueError("在线检索需要至少一个查询词")
        per_query = min(max(int(top_k), 1), 40)
        merged: dict[str, dict[str, Any]] = {}
        for search_query in query_list:
            for paper in self._online_search_one(search_query, per_query, year_from=year_from):
                key = str(paper.get("doi") or paper.get("openalex_id") or paper.get("title") or "").lower()
                if not key:
                    continue
                if key not in merged:
                    paper["matched_queries"] = [search_query]
                    paper["abstract_complete"] = bool(paper.get("abstract"))
                    merged[key] = paper
                elif search_query not in merged[key]["matched_queries"]:
                    merged[key]["matched_queries"].append(search_query)
        papers = sorted(
            merged.values(),
            key=lambda item: (
                len(item.get("matched_queries", [])),
                item.get("relevance_score") or 0,
                item.get("cited_by_count") or 0,
            ),
            reverse=True,
        )
        lines = [
            f"执行 {len(query_list)} 个独立 OpenAlex 查询，去重后得到 {len(papers)} 篇候选论文。",
            (f"年份范围：{year_from} 年至今。" if year_from else "年份范围：未限制。"),
            f"每个查询最多取相关度排序前 {per_query} 条；这是候选集，不代表领域里只有这些论文。",
            "在线阅读范围：题名、作者、年份、DOI、来源字段，以及 OpenAlex 提供时的完整索引摘要；未下载全文。",
            "",
            "查询计划：",
            *[f"- {item}" for item in query_list],
            "",
        ]
        for index, paper in enumerate(papers, start=1):
            title = paper.get("title") or "Untitled"
            year = paper.get("year") or "?"
            doi = paper.get("doi") or ""
            matched = "; ".join(paper.get("matched_queries", []))
            abstract_scope = "完整 OpenAlex 摘要" if paper.get("abstract_complete") else "无摘要，仅元数据"
            lines.append(
                f"{index}. {title} ({year})" + (f" — {doi}" if doi else "")
                + f" — {abstract_scope} — 命中查询：{matched}"
            )
        return AdapterResult("online_search", "\n".join(lines), [], papers)
