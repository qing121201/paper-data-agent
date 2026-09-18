from __future__ import annotations

from dataclasses import asdict, dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import uuid
from typing import Any

from .adapters import ResearchToolAdapters
from .web_sources import probe_public_url


SORT_COMBINED = "综合推荐"
SORT_NEWEST = "最新发表"
SORT_CITATIONS = "引用量"
SORT_RELEVANCE = "相关性"
SORT_MODES = (SORT_COMBINED, SORT_NEWEST, SORT_CITATIONS, SORT_RELEVANCE)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]


def _venue_matches(requested: str, actual: str) -> bool:
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


def _expand_topic(topic: str) -> list[str]:
    """Add a small transparent bilingual query expansion for common home-page topics."""
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
    def from_form(cls, name: str, topics: str, venues: str, count: int, recency_days: int,
                  subscription_id: str = "") -> "DiscoverySubscription":
        return cls(name, _split_terms(topics), _split_terms(venues), count, recency_days,
                   subscription_id or uuid.uuid4().hex).normalized()


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


class DiscoveryStore:
    """Local subscriptions and daily result cache. No API key or paper text is stored here."""

    def __init__(self, settings_path: Path, cache_path: Path):
        self.settings_path = settings_path
        self.cache_path = cache_path

    def load_subscriptions(self) -> list[DiscoverySubscription]:
        if not self.settings_path.is_file():
            return []
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return [DiscoverySubscription(**item).normalized() for item in payload.get("subscriptions", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def save_subscriptions(self, subscriptions: list[DiscoverySubscription]) -> None:
        _write_json(self.settings_path, {"subscriptions": [asdict(item.normalized()) for item in subscriptions]})

    @staticmethod
    def cache_key(subscription: DiscoverySubscription, sort_mode: str) -> str:
        raw = json.dumps(asdict(subscription.normalized()), ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256((raw + sort_mode).encode("utf-8")).hexdigest()[:16]
        return f"{date.today().isoformat()}:v3:{digest}"

    def load_cached(self, subscription: DiscoverySubscription, sort_mode: str) -> list[DiscoveryPaper] | None:
        if not self.cache_path.is_file():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            items = payload.get(self.cache_key(subscription, sort_mode))
            return [DiscoveryPaper(**item) for item in items] if isinstance(items, list) else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save_cached(self, subscription: DiscoverySubscription, sort_mode: str,
                    papers: list[DiscoveryPaper]) -> None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.is_file() else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            payload = {}
        payload = {key: value for key, value in payload.items() if key.startswith(date.today().isoformat() + ":")}
        payload[self.cache_key(subscription, sort_mode)] = [asdict(item) for item in papers]
        _write_json(self.cache_path, payload)


class DiscoveryService:
    def __init__(self, output_dir: Path):
        self.adapters = ResearchToolAdapters(output_dir)
        self.url_probe = probe_public_url

    def recommend(self, subscription: DiscoverySubscription, sort_mode: str = SORT_COMBINED) -> list[DiscoveryPaper]:
        subscription = subscription.normalized()
        if not subscription.topics and not subscription.venues:
            raise ValueError("请先在订阅设置中填写至少一个标签、期刊或会议")
        sort_mode = sort_mode if sort_mode in SORT_MODES else SORT_COMBINED
        expanded_topics = list(dict.fromkeys(query for topic in subscription.topics for query in _expand_topic(topic)))
        if expanded_topics and subscription.venues:
            queries = [f"{topic} {venue}" for topic in expanded_topics[:2]
                       for venue in subscription.venues[:2]]
            queries.extend(expanded_topics)
        elif expanded_topics:
            queries = expanded_topics
        else:
            queries = list(subscription.venues)
        queries = list(dict.fromkeys(queries))[:4]
        year_from = (date.today() - timedelta(days=subscription.recency_days)).year
        result = self.adapters.online_search(queries[-1], top_k=40, queries=queries[:-1], year_from=year_from)
        raw_papers = result.data if isinstance(result.data, list) else []
        papers = self._score(raw_papers, subscription)
        expanded_papers: list[DiscoveryPaper] = []
        if subscription.recency_days < 365:
            # A narrow recent window can contain too few cited papers. Fill the
            # remaining slots from the same already-fetched yearly candidate pool,
            # while keeping the actual publication date visible in the UI.
            expanded = DiscoverySubscription(
                subscription.name, subscription.topics, subscription.venues,
                subscription.count, 365, subscription.subscription_id,
            )
            seen = {item.paper_key for item in papers}
            expanded_papers = [item for item in self._score(raw_papers, expanded) if item.paper_key not in seen]
        key = {
            SORT_COMBINED: lambda item: (item.combined_score, item.publication_date),
            SORT_NEWEST: lambda item: (item.publication_date, item.combined_score),
            SORT_CITATIONS: lambda item: (item.cited_by_count, item.relevance_score),
            SORT_RELEVANCE: lambda item: (item.relevance_score, item.cited_by_count),
        }[sort_mode]
        papers.sort(key=key, reverse=True)
        expanded_papers.sort(key=key, reverse=True)
        return self._verify_and_select(papers + expanded_papers, subscription.count)

    def _verify_and_select(self, papers: list[DiscoveryPaper], count: int) -> list[DiscoveryPaper]:
        candidates = papers[:min(max(count * 2, 8), 20)]
        unique_urls = list(dict.fromkeys(paper.landing_url for paper in candidates
                                        if paper.landing_url and paper.landing_url != "None"))
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
    def _score(raw_papers: list[dict[str, Any]], subscription: DiscoverySubscription) -> list[DiscoveryPaper]:
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
                # OpenAlex can retain deleted/spam Zenodo metadata as open access.
                # Zero-citation metadata-only deposits are poor daily-paper candidates.
                continue
            haystack = f"{title} {item.get('abstract') or ''} {venue}".casefold()
            topic_hits = sum(term in haystack for term in topic_terms)
            venue_hits = sum(_venue_matches(term, venue) for term in venue_terms)
            if venue_terms and topic_terms and not (topic_hits or venue_hits):
                continue
            matched = list(item.get("matched_queries") or [])
            if venue_terms and not venue_hits:
                continue
            relevance = min(1.0, (topic_hits + venue_hits * 1.25 + len(matched) * .5)
                            / max(len(topic_terms) + len(venue_terms), 1))
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
            doi_url = (doi if doi.lower().startswith(("http://", "https://"))
                       else f"https://doi.org/{doi}" if doi else "")
            landing = str(doi_url or item.get("landing_url") or item.get("openalex_id") or "")
            output.append(DiscoveryPaper(
                paper_key=key, title=str(item.get("title")), authors=[str(x) for x in item.get("authors") or []],
                publication_date=str(item.get("publication_date") or ""),
                year=int(item["year"]) if str(item.get("year") or "").isdigit() else None,
                venue=str(item.get("journal") or ""), cited_by_count=citations,
                abstract=str(item.get("abstract") or ""), doi=doi,
                openalex_id=str(item.get("openalex_id") or ""), public_url=urls[0] if urls else "",
                public_urls=list(dict.fromkeys(urls)), landing_url=landing, link_verified=False,
                matched_queries=list(item.get("matched_queries") or []),
                relevance_score=round(relevance, 4), freshness_score=round(freshness, 4),
                citation_score=round(citation_score, 4),
                combined_score=round(combined, 4),
            ))
        return output
