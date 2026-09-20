"""Online paper discovery, ranking, and resilient public-full-text import."""

from __future__ import annotations

import re

from .models import SearchImportResult


class OnlineImportMixin:
    """Add bounded OpenAlex search-and-import behavior to a paper repository."""

    def search_and_import(
        self, query: str, top_k: int = 5, queries: list[str] | None = None,
        year_from: int | None = None,
    ) -> SearchImportResult:
        from ..adapters import ResearchToolAdapters

        target = min(max(int(top_k), 1), 10)
        candidate_target = min(max(target * 4, 20), 40)
        cleaned_queries = self._clean_queries([*(queries or []), query])
        primary = cleaned_queries[-1] if cleaned_queries else query
        search = ResearchToolAdapters(self.path / "outputs").online_search(
            primary, top_k=candidate_target, queries=cleaned_queries[:-1], year_from=year_from)
        candidates = search.data if isinstance(search.data, list) else []
        papers = self._rank_candidates(candidates, cleaned_queries, candidate_target)

        added = duplicates = failed = downloadable = 0
        titles: list[str] = []
        imported_details: list[dict[str, object]] = []
        failures: list[str] = []
        for paper in papers:
            if added >= target:
                break
            urls = self._public_urls(paper)
            title = str(paper.get("title") or "未命名论文")
            if not urls:
                failures.append(f"《{title}》：OpenAlex 未提供公开地址")
                continue
            downloadable += 1
            imported, result, errors, attempted, details = self._try_import_candidate(paper, urls)
            added += result.added
            duplicates += result.duplicates
            if result.added:
                titles.append(title)
                imported_details.append(details)
            if not imported:
                failed += 1
                hosts = []
                for attempted_url in attempted:
                    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", attempted_url).split("/", 1)[0])
                    if host and host not in hosts:
                        hosts.append(host)
                reason = errors[-1] if errors else "所有公开地址均无法导入"
                failures.append(f"《{title}》：尝试 {', '.join(hosts) or '公开地址'}；{reason}")
        return SearchImportResult(
            "；".join(cleaned_queries), len(papers), downloadable, added, duplicates,
            failed, titles, failures, year_from, target, imported_details,
        )

    @staticmethod
    def _clean_queries(raw_queries: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in raw_queries:
            value = re.sub(r"(?i)\bopen\s+access\b", "", str(value))
            value = re.sub(r"\s+", " ", value).strip()
            if value and value.lower() not in {item.lower() for item in cleaned}:
                cleaned.append(value)
        return cleaned[:4]

    @staticmethod
    def _rank_candidates(
        candidates: list[dict[str, object]], cleaned_queries: list[str], limit: int,
    ) -> list[dict[str, object]]:
        stop = {
            "open", "access", "review", "paper", "model", "models", "study", "analysis",
            "computational", "biology", "related", "latest", "recent", "simulation",
        }
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
            ranked.append((
                phrase_bonus, score, int(paper.get("cited_by_count") or 0),
                int("review" in title_lower), paper,
            ))
        ranked.sort(key=lambda row: row[:4], reverse=True)
        return [row[-1] for row in ranked[:limit]]

    @staticmethod
    def _public_urls(paper: dict[str, object]) -> list[str]:
        urls = []
        for value in [paper.get("open_access_url"), *(paper.get("open_access_urls") or [])]:
            value = str(value or "").strip()
            if value and value not in urls:
                urls.append(value)
        expanded = []
        for url in urls:
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
        output = list(dict.fromkeys(expanded))
        output.sort(key=OnlineImportMixin._url_priority, reverse=True)
        return output

    @staticmethod
    def _url_priority(value: str) -> tuple[int, int]:
        lower = value.lower()
        repository = any(host in lower for host in (
            "arxiv.org", "pmc.ncbi.nlm.nih.gov", "europepmc.org",
            "biorxiv.org", "medrxiv.org", "zenodo.org", "repository", "hal.science",
        ))
        direct_pdf = lower.endswith(".pdf") or "/pdf/" in lower or "showpdf" in lower
        landing = "doi.org/" in lower or "pubmed.ncbi.nlm.nih.gov" in lower
        return (int(repository) * 4 + int(direct_pdf) * 2 - int(landing) * 3, -len(value))

    def _try_import_candidate(
        self, paper: dict[str, object], urls: list[str],
    ) -> tuple[bool, object, list[str], list[str], dict[str, object]]:
        title = str(paper.get("title") or "未命名论文")
        raw_authors = paper.get("authors") or []
        authors = [str(name) for name in raw_authors] if isinstance(raw_authors, list) else [str(raw_authors)]
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(paper.get("doi") or ""), flags=re.I)
        raw_year = paper.get("year")
        year = int(raw_year) if str(raw_year or "").isdigit() else None
        raw_citations = paper.get("cited_by_count")
        citations = int(raw_citations) if str(raw_citations or "").isdigit() else None
        errors: list[str] = []
        attempted: list[str] = []
        result = None
        public_url = ""
        for url in urls[:5]:
            attempted.append(url)
            try:
                result = self.import_url(
                    url, title_override=title, authors=authors, year=year,
                    doi=doi, cited_by_count=citations,
                )
                if result.added or result.duplicates:
                    public_url = url
                    break
                errors.extend(result.failures)
            except Exception as exc:
                errors.append(str(exc))
        if result is None:
            from .models import ImportResult
            result = ImportResult(0, 0, 1, errors)
        details = {
            "title": title, "authors": authors, "year": year, "doi": doi,
            "cited_by_count": citations, "public_url": public_url,
        }
        return bool(result.added or result.duplicates), result, errors, attempted, details
