"""OpenAlex candidate collection, ranking, public-link checks, and selection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..adapters import ResearchToolAdapters
from ..web_sources import probe_public_url
from .models import (
    SORT_CITATIONS,
    SORT_COMBINED,
    SORT_MODES,
    SORT_NEWEST,
    SORT_RELEVANCE,
    DiscoveryPaper,
    DiscoverySubscription,
)
from .scoring import expand_topic, score_papers


class DiscoveryService:
    def __init__(self, output_dir: Path):
        self.adapters = ResearchToolAdapters(output_dir)
        self.url_probe = probe_public_url

    def recommend(
        self, subscription: DiscoverySubscription, sort_mode: str = SORT_COMBINED,
    ) -> list[DiscoveryPaper]:
        subscription = subscription.normalized()
        if not subscription.topics and not subscription.venues:
            raise ValueError("请先在订阅设置中填写至少一个标签、期刊或会议")
        sort_mode = sort_mode if sort_mode in SORT_MODES else SORT_COMBINED
        queries = self._queries(subscription)
        year_from = (date.today() - timedelta(days=subscription.recency_days)).year
        result = self.adapters.online_search(
            queries[-1], top_k=40, queries=queries[:-1], year_from=year_from,
        )
        raw_papers = result.data if isinstance(result.data, list) else []
        papers = self._score(raw_papers, subscription)
        expanded_papers: list[DiscoveryPaper] = []
        if subscription.recency_days < 365:
            expanded = DiscoverySubscription(
                subscription.name, subscription.topics, subscription.venues,
                subscription.count, 365, subscription.subscription_id,
            )
            seen = {item.paper_key for item in papers}
            expanded_papers = [
                item for item in self._score(raw_papers, expanded) if item.paper_key not in seen
            ]
        key = {
            SORT_COMBINED: lambda item: (item.combined_score, item.publication_date),
            SORT_NEWEST: lambda item: (item.publication_date, item.combined_score),
            SORT_CITATIONS: lambda item: (item.cited_by_count, item.relevance_score),
            SORT_RELEVANCE: lambda item: (item.relevance_score, item.cited_by_count),
        }[sort_mode]
        papers.sort(key=key, reverse=True)
        expanded_papers.sort(key=key, reverse=True)
        return self._verify_and_select(papers + expanded_papers, subscription.count)

    @staticmethod
    def _queries(subscription: DiscoverySubscription) -> list[str]:
        topics = list(dict.fromkeys(
            query for topic in subscription.topics for query in expand_topic(topic)
        ))
        if topics and subscription.venues:
            queries = [
                f"{topic} {venue}" for topic in topics[:2] for venue in subscription.venues[:2]
            ]
            queries.extend(topics)
        elif topics:
            queries = topics
        else:
            queries = list(subscription.venues)
        return list(dict.fromkeys(queries))[:4]

    def _verify_and_select(self, papers: list[DiscoveryPaper], count: int) -> list[DiscoveryPaper]:
        candidates = papers[:min(max(count * 2, 8), 20)]
        unique_urls = list(dict.fromkeys(
            paper.landing_url for paper in candidates
            if paper.landing_url and paper.landing_url != "None"
        ))
        statuses: dict[str, tuple[bool, str]] = {}
        with ThreadPoolExecutor(max_workers=min(10, len(unique_urls) or 1)) as executor:
            futures = {executor.submit(self.url_probe, url): url for url in unique_urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    status = future.result()
                    statuses[url] = (bool(status.available), status.final_url)
                except Exception:
                    statuses[url] = (False, "")

        verified: list[DiscoveryPaper] = []
        metadata_only: list[DiscoveryPaper] = []
        for paper in candidates:
            landing_available, landing_final = statuses.get(paper.landing_url, (False, ""))
            paper.public_urls = list(dict.fromkeys(paper.public_urls)) if landing_available else []
            paper.public_url = paper.public_urls[0] if paper.public_urls else ""
            paper.link_verified = bool(landing_available)
            paper.landing_url = (landing_final or paper.landing_url) if landing_available else paper.openalex_id
            (verified if paper.link_verified else metadata_only).append(paper)
        return (verified + metadata_only)[:count]

    @staticmethod
    def _score(
        raw_papers: list[dict[str, Any]], subscription: DiscoverySubscription,
    ) -> list[DiscoveryPaper]:
        return score_papers(raw_papers, subscription)
