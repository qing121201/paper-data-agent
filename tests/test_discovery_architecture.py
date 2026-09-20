import unittest

from paper_data_agent import discovery
from paper_data_agent.discovery_domain import models, service, store


class DiscoveryArchitectureTests(unittest.TestCase):
    def test_compatibility_facade_reexports_domain_types(self) -> None:
        self.assertIs(discovery.DiscoveryService, service.DiscoveryService)
        self.assertIs(discovery.DiscoveryStore, store.DiscoveryStore)
        self.assertIs(discovery.DiscoverySubscription, models.DiscoverySubscription)
        self.assertIs(discovery.DiscoveryPaper, models.DiscoveryPaper)

    def test_store_has_no_ui_or_network_dependencies(self) -> None:
        self.assertNotIn("tkinter", store.__dict__)
        self.assertNotIn("ResearchToolAdapters", store.__dict__)
        self.assertNotIn("probe_public_url", store.__dict__)


if __name__ == "__main__":
    unittest.main()
