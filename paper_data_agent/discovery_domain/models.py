"""Stable subscription and paper records used by discovery services and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import uuid


SORT_COMBINED = "综合推荐"
SORT_NEWEST = "最新发表"
SORT_CITATIONS = "引用量"
SORT_RELEVANCE = "相关性"
SORT_MODES = (SORT_COMBINED, SORT_NEWEST, SORT_CITATIONS, SORT_RELEVANCE)


def split_terms(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]


@dataclass(slots=True)
class DiscoverySubscription:
    name: str = "我的关注"
    topics: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    count: int = 5
    recency_days: int = 90
    subscription_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def normalized(self) -> "DiscoverySubscription":
        return DiscoverySubscription(
            name=self.name.strip() or "我的关注",
            topics=list(dict.fromkeys(item for item in (x.strip() for x in self.topics) if item))[:8],
            venues=list(dict.fromkeys(item for item in (x.strip() for x in self.venues) if item))[:8],
            count=min(max(int(self.count), 2), 10),
            recency_days=min(max(int(self.recency_days), 7), 730),
            subscription_id=self.subscription_id or uuid.uuid4().hex,
        )

    @classmethod
    def from_form(
        cls, name: str, topics: str, venues: str, count: int, recency_days: int,
        subscription_id: str = "",
    ) -> "DiscoverySubscription":
        return cls(
            name, split_terms(topics), split_terms(venues), count, recency_days,
            subscription_id or uuid.uuid4().hex,
        ).normalized()


@dataclass(slots=True)
class DiscoveryPaper:
    paper_key: str
    title: str
    authors: list[str]
    publication_date: str
    year: int | None
    venue: str
    cited_by_count: int
    abstract: str
    doi: str
    openalex_id: str
    public_url: str
    public_urls: list[str]
    landing_url: str
    link_verified: bool
    matched_queries: list[str]
    relevance_score: float
    freshness_score: float
    citation_score: float
    combined_score: float

    @property
    def downloadable(self) -> bool:
        return bool(self.public_url or self.public_urls)
