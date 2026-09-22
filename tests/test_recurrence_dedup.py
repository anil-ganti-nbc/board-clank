from __future__ import annotations

from board_clank.fixtures import load_scenario, scenario_to_request
from board_clank.models import CollectorRunRequest
from board_clank.pipeline import Pipeline
from board_clank.store import Store


def test_recurring_transition_gets_new_event_identity(pipeline: Pipeline, store: Store) -> None:
    runs = scenario_to_request(load_scenario("K"))
    for req in runs:
        pipeline.accept_run(req)
    # Replay the B payload again as a new run after returning to A.
    b_run = runs[1]
    again = CollectorRunRequest(
        run_id="K-B2",
        source_key=b_run.source_key,
        collector_key=b_run.collector_key,
        started_at="2026-04-01T00:00:00+00:00",
        observations=b_run.observations,
        fixture_scenario="K",
    )
    pipeline.accept_run(again)
    rows = store.all(
        "SELECT event_key, run_id FROM events WHERE event_type = 'PORTS_CHANGED' ORDER BY event_id"
    )
    assert len(rows) >= 2
    keys = [row["event_key"] for row in rows]
    assert len(set(keys)) == len(keys)
