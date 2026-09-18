from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from paper_data_agent.adapters import AdapterResult
from paper_data_agent.discovery import (
    DiscoveryService, DiscoveryStore, DiscoverySubscription,
    SORT_CITATIONS, SORT_COMBINED, SORT_NEWEST,
)
from paper_data_agent.web_sources import PublicURLStatus


class DiscoveryTests(unittest.TestCase):
    @staticmethod
    def _papers():
        today = date.today()
        return [
            {
                "title": "Fresh Agent Paper", "authors": ["A"],
                "publication_date": (today - timedelta(days=2)).isoformat(), "year": today.year,
                "journal": "NeurIPS", "cited_by_count": 2, "abstract": "AI agent planning",
                "doi": "10.1/fresh", "openalex_id": "W1", "open_access_url": "https://x/fresh.pdf",
                "open_access_urls": ["https://x/fresh.pdf"], "matched_queries": ["AI agent NeurIPS"],
            },
            {
                "title": "Established Agent Paper", "authors": ["B"],
                "publication_date": (today - timedelta(days=40)).isoformat(), "year": today.year,
                "journal": "NeurIPS", "cited_by_count": 200, "abstract": "AI agent tools",
                "doi": "10.1/cited", "openalex_id": "W2", "open_access_url": "https://x/cited.pdf",
                "open_access_urls": ["https://x/cited.pdf"], "matched_queries": ["AI agent NeurIPS"],
            },
            {
                "title": "Wrong Venue", "authors": ["C"],
                "publication_date": today.isoformat(), "year": today.year,
                "journal": "Other Journal", "cited_by_count": 999, "abstract": "AI agent",
                "doi": "10.1/wrong", "openalex_id": "W3", "open_access_url": "https://x/wrong.pdf",
                "open_access_urls": ["https://x/wrong.pdf"], "matched_queries": ["AI agent"],
            },
        ]

    def _service(self):
        service = DiscoveryService(Path("output"))
        papers = self._papers()
        service.adapters.online_search = lambda *args, **kwargs: AdapterResult("online_search", "", [], papers)
        service.url_probe = lambda url: PublicURLStatus(True, 200, url)
        return service

    def test_sort_modes_and_venue_filter(self):
        subscription = DiscoverySubscription("Agents", ["AI agent"], ["NeurIPS"], 5, 90)
        service = self._service()
        newest = service.recommend(subscription, SORT_NEWEST)
        cited = service.recommend(subscription, SORT_CITATIONS)
        self.assertEqual([item.title for item in newest], ["Fresh Agent Paper", "Established Agent Paper"])
        self.assertEqual(cited[0].title, "Established Agent Paper")
        self.assertTrue(all(item.venue == "NeurIPS" for item in cited))

    def test_common_conference_acronym_matches_openalex_source_name(self):
        papers = self._papers()
        papers[0]["journal"] = "Advances in Neural Information Processing Systems"
        service = DiscoveryService(Path("output"))
        service.adapters.online_search = lambda *args, **kwargs: AdapterResult("online_search", "", [], papers)
        service.url_probe = lambda url: PublicURLStatus(True, 200, url)
        result = service.recommend(DiscoverySubscription("Agents", ["AI agent"], ["NeurIPS"], 3, 90))
        self.assertIn("Fresh Agent Paper", [item.title for item in result])

    def test_venue_is_included_in_search_query_before_topic_only_fallbacks(self):
        service = DiscoveryService(Path("output"))
        calls = []
        service.adapters.online_search = lambda query, **kwargs: (
            calls.append((query, kwargs.get("queries"))) or AdapterResult("online_search", "", [], self._papers())
        )
        service.url_probe = lambda url: PublicURLStatus(True, 200, url)
        service.recommend(DiscoverySubscription("Agents", ["AI agent", "tool use"], ["NeurIPS"], 3, 90))
        flattened = [*(calls[0][1] or []), calls[0][0]]
        self.assertTrue(any("AI agent NeurIPS" == item for item in flattened))

    def test_common_chinese_topic_adds_english_openalex_query(self):
        service = DiscoveryService(Path("output"))
        calls = []
        service.adapters.online_search = lambda query, **kwargs: (
            calls.append((query, kwargs.get("queries"))) or AdapterResult("online_search", "", [], self._papers())
        )
        service.url_probe = lambda url: PublicURLStatus(True, 200, url)
        service.recommend(DiscoverySubscription("多模态", ["多模态学习"], [], 3, 90))
        flattened = [*(calls[0][1] or []), calls[0][0]]
        self.assertIn("multimodal learning", flattened)

    def test_combined_scores_are_explainable_and_urls_survive(self):
        papers = self._service().recommend(DiscoverySubscription("Agents", ["AI agent"], [], 5, 90), SORT_COMBINED)
        self.assertTrue(all(0 <= item.freshness_score <= 1 for item in papers))
        self.assertTrue(all(0 <= item.citation_score <= 1 for item in papers))
        self.assertTrue(all(0 <= item.relevance_score <= 1 for item in papers))
        self.assertTrue(all(item.downloadable for item in papers))

    def test_subscription_and_daily_cache_round_trip(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            store = DiscoveryStore(root / "subscriptions.json", root / "cache.json")
            subscription = DiscoverySubscription.from_form("Bio", "virtual cell，protein", "Nature", 8, 3)
            self.assertEqual(subscription.count, 8)
            self.assertEqual(subscription.recency_days, 7)
            store.save_subscriptions([subscription])
            loaded = store.load_subscriptions()
            self.assertEqual(asdict(loaded[0]), asdict(subscription))
            papers = self._service().recommend(DiscoverySubscription("Agents", ["AI agent"], [], 3, 90))
            store.save_cached(subscription, SORT_COMBINED, papers)
            self.assertEqual([item.title for item in store.load_cached(subscription, SORT_COMBINED) or []],
                             [item.title for item in papers])

    def test_count_is_clamped_to_two_through_ten(self):
        self.assertEqual(DiscoverySubscription.from_form("a", "x", "", 1, 30).count, 2)
        self.assertEqual(DiscoverySubscription.from_form("b", "x", "", 99, 30).count, 10)

    def test_dead_external_link_falls_back_to_openalex_and_ranks_after_live_link(self):
        service = self._service()
        service.url_probe = lambda url: PublicURLStatus("fresh" in url, 200 if "fresh" in url else 410, url)
        papers = service.recommend(DiscoverySubscription("Agents", ["AI agent"], [], 3, 90), SORT_COMBINED)
        self.assertEqual(papers[0].title, "Fresh Agent Paper")
        dead = next(item for item in papers if item.title == "Established Agent Paper")
        self.assertFalse(dead.link_verified)
        self.assertEqual(dead.landing_url, dead.openalex_id)
        self.assertFalse(dead.public_urls)


if __name__ == "__main__":
    unittest.main()
