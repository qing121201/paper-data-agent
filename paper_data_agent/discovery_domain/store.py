"""Local subscription persistence and date-scoped recommendation cache."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path

from .models import DiscoveryPaper, DiscoverySubscription


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class DiscoveryStore:
    """Local subscriptions and daily result cache; stores no key or paper text."""

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
        write_json(self.settings_path, {"subscriptions": [asdict(item.normalized()) for item in subscriptions]})

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

    def save_cached(
        self, subscription: DiscoverySubscription, sort_mode: str, papers: list[DiscoveryPaper],
    ) -> None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.is_file() else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            payload = {}
        prefix = date.today().isoformat() + ":"
        payload = {key: value for key, value in payload.items() if key.startswith(prefix)}
        payload[self.cache_key(subscription, sort_mode)] = [asdict(item) for item in papers]
        write_json(self.cache_path, payload)
