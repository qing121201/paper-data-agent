"""Transparent topic expansion, venue matching, filtering, and ranking scores."""

from __future__ import annotations

from datetime import date
import math
import re
from typing import Any

from .models import DiscoveryPaper, DiscoverySubscription


def venue_matches(requested: str, actual: str) -> bool:
    wanted = re.sub(r"[^a-z0-9]+", " ", requested.casefold()).strip()
    venue = re.sub(r"[^a-z0-9]+", " ", actual.casefold()).strip()
    if not wanted or not venue:
        return False
    if wanted in venue or venue in wanted:
        return True
    aliases = {
        "neurips": "neural information processing systems",
        "nips": "neural information processing systems",
        "icml": "international conference on machine learning",
        "iclr": "international conference on learning representations",
        "cvpr": "computer vision and pattern recognition",
        "acl": "association for computational linguistics",
        "emnlp": "empirical methods in natural language processing",
        "aaai": "association for the advancement of artificial intelligence",
        "ijcai": "international joint conference on artificial intelligence",
    }
    expanded = aliases.get(wanted)
    return bool(expanded and expanded in venue)


def expand_topic(topic: str) -> list[str]:
    mappings = {
        "多模态": "multimodal learning",
        "大语言模型": "large language models",
        "语言模型": "large language models",
        "计算机视觉": "computer vision",
        "自然语言处理": "natural language processing",
        "虚拟细胞": "virtual cell computational biology",
        "脑科学": "neuroscience fMRI",
        "具身智能": "embodied artificial intelligence",
        "智能体": "AI agents",
    }
    expanded = [topic]
    for needle, english in mappings.items():
        if needle in topic and english.casefold() not in {item.casefold() for item in expanded}:
            expanded.append(english)
    return expanded


def score_papers(
    raw_papers: list[dict[str, Any]], subscription: DiscoverySubscription,
) -> list[DiscoveryPaper]:
    today = date.today()
    candidates: list[tuple[dict[str, Any], int, float, float, float, float]] = []
    max_citations = max((int(item.get("cited_by_count") or 0) for item in raw_papers), default=0)
    venue_terms = [item.casefold() for item in subscription.venues]
    topic_terms = [item.casefold() for item in subscription.topics]
    for item in raw_papers:
        if item.get("is_retracted"):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        venue = str(item.get("journal") or "").strip()
        citations = int(item.get("cited_by_count") or 0)
        raw_urls = [str(value) for value in [item.get("open_access_url"), *(item.get("open_access_urls") or [])] if value]
        has_direct_pdf = any(url.lower().endswith(".pdf") or "/pdf/" in url.lower() for url in raw_urls)
        if "zenodo" in venue.casefold() and citations == 0 and not has_direct_pdf:
            continue
        haystack = f"{title} {item.get('abstract') or ''} {venue}".casefold()
        topic_hits = sum(term in haystack for term in topic_terms)
        venue_hits = sum(venue_matches(term, venue) for term in venue_terms)
        if venue_terms and topic_terms and not (topic_hits or venue_hits):
            continue
        matched = list(item.get("matched_queries") or [])
        if venue_terms and not venue_hits:
            continue
        relevance = min(
            1.0,
            (topic_hits + venue_hits * 1.25 + len(matched) * .5)
            / max(len(topic_terms) + len(venue_terms), 1),
        )
        published = str(item.get("publication_date") or "")
        try:
            age_days = max((today - date.fromisoformat(published)).days, 0)
            date_is_exact = True
        except ValueError:
            year = item.get("year")
            age_days = max((today - date(int(year), 7, 1)).days, 0) if str(year or "").isdigit() else subscription.recency_days
            date_is_exact = False
        if age_days > subscription.recency_days + (0 if date_is_exact else 366):
            continue
        freshness = max(0.0, 1.0 - age_days / max(subscription.recency_days, 1))
        citation_score = math.log1p(citations) / math.log1p(max_citations) if max_citations else 0.0
        combined = freshness * .35 + citation_score * .30 + relevance * .35
        candidates.append((item, citations, relevance, freshness, citation_score, combined))

    output: list[DiscoveryPaper] = []
    seen: set[str] = set()
    seen_titles: set[str] = set()
    for item, citations, relevance, freshness, citation_score, combined in candidates:
        key = str(item.get("doi") or item.get("openalex_id") or item.get("title")).casefold()
        title_key = re.sub(r"\W+", "", str(item.get("title") or "").casefold())
        if key in seen or title_key in seen_titles:
            continue
        seen.add(key)
        seen_titles.add(title_key)
        urls = [str(value) for value in [item.get("open_access_url"), *(item.get("open_access_urls") or [])] if value]
        doi = str(item.get("doi") or "")
        doi_url = doi if doi.lower().startswith(("http://", "https://")) else f"https://doi.org/{doi}" if doi else ""
        landing = str(doi_url or item.get("landing_url") or item.get("openalex_id") or "")
        output.append(DiscoveryPaper(
            paper_key=key,
            title=str(item.get("title")),
            authors=[str(x) for x in item.get("authors") or []],
            publication_date=str(item.get("publication_date") or ""),
            year=int(item["year"]) if str(item.get("year") or "").isdigit() else None,
            venue=str(item.get("journal") or ""),
            cited_by_count=citations,
            abstract=str(item.get("abstract") or ""),
            doi=doi,
            openalex_id=str(item.get("openalex_id") or ""),
            public_url=urls[0] if urls else "",
            public_urls=list(dict.fromkeys(urls)),
            landing_url=landing,
            link_verified=False,
            matched_queries=list(item.get("matched_queries") or []),
            relevance_score=round(relevance, 4),
            freshness_score=round(freshness, 4),
            citation_score=round(citation_score, 4),
            combined_score=round(combined, 4),
        ))
    return output
