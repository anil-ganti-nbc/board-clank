from __future__ import annotations
from board_clank.fixtures import load_scenario, scenario_to_request
from board_clank.models import CollectorRunRequest
from board_clank.taxonomy import PHASE1_VENDORS
class InertVendorAdapter:
    live_network = False
    def __init__(self, vendor, source_key):
        self.vendor = vendor
        self.source_key = source_key
        self.collector_key = f"{vendor}-inert"
    def collect(self, run_id, started_at):
        return CollectorRunRequest(run_id=run_id, source_key=self.source_key, collector_key=self.collector_key, started_at=started_at, observations=[], ok=True)
class FixtureCollector:
    live_network = False
    collector_key = "fixture"
    def __init__(self, scenario):
        self.scenario = scenario
    def collect_runs(self):
        return scenario_to_request(load_scenario(self.scenario))
ADAPTERS = {vendor: InertVendorAdapter(vendor, f"{vendor}-product") for vendor in PHASE1_VENDORS}
def get_adapter(source_key):
    vendor = source_key.replace("-product", "")
    return ADAPTERS[vendor]
