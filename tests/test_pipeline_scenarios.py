from __future__ import annotations

from board_clank.pipeline import Pipeline
from board_clank.store import Store
from conftest import run_scenario


def event_types(store: Store) -> list[str]:
    return [row["event_type"] for row in store.all("SELECT event_type FROM events ORDER BY event_id")]


def live_event_types(store: Store) -> list[str]:
    return [
        row["event_type"]
        for row in store.all("SELECT event_type FROM events WHERE baseline_silent = 0 ORDER BY event_id")
    ]


def test_A_unchanged_repeat_is_sighting_only(pipeline: Pipeline, store: Store) -> None:
    results = run_scenario(pipeline, "A")
    assert results[0].baseline is True
    assert results[1].baseline is False
    assert store.count("boards") == 1
    assert store.count("observation_occurrences") >= 2
    assert "NEW_BOARD" not in live_event_types(store)
    current = store.count("current_entity_observations")
    assert current >= 1


def test_B_new_ram_variant_keeps_one_board(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "B")
    assert store.count("boards") == 1
    assert store.count("board_variants") == 2
    assert "RAM_VARIANT_ADDED" in live_event_types(store)
    assert "NEW_BOARD" not in live_event_types(store)


def test_C_explicit_revision_same_product_name(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "C")
    assert store.count("boards") == 1
    assert store.count("board_revisions") == 2
    assert "BOARD_REVISION" in live_event_types(store)


def test_D_silent_revision_ports(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "D")
    assert store.count("boards") == 1
    assert store.count("board_revisions") == 2
    live = live_event_types(store)
    assert "BOARD_REVISION" in live or "PORTS_CHANGED" in live


def test_E_historical_store_page_is_not_new_board(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "E")
    assert store.count("boards") == 1
    types = event_types(store)
    assert "NEW_BOARD" not in types
    novelty = store.one("SELECT novelty_status, first_seen_at, official_announcement_at FROM novelty_evidence")
    assert novelty["novelty_status"] == "HISTORICAL"
    assert novelty["first_seen_at"] != novelty["official_announcement_at"]


def test_F_docs_plane_does_not_imply_launch(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "F")
    occ = store.one("SELECT plane FROM observation_occurrences")
    assert occ["plane"] == "DOCUMENTATION"
    novelty = store.one("SELECT novelty_status, docs_date, official_announcement_at FROM novelty_evidence")
    assert novelty["official_announcement_at"] == "UNKNOWN"
    assert novelty["docs_date"] != "UNKNOWN"


def test_G_soc_change(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "G")
    assert store.count("socs") == 2
    assert "SOC_CHANGED" in live_event_types(store)


def test_H_price_only_review_not_push(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "H")
    assert "PRICE_CHANGED" in live_event_types(store)
    row = store.one(
        """
        SELECT n.disposition FROM notifications n
        JOIN events e ON e.event_key = n.event_key
        WHERE e.event_type = 'PRICE_CHANGED'
        """
    )
    assert row["disposition"] == "REVIEW"


def test_I_availability_only(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "I")
    assert "AVAILABILITY_CHANGED" in live_event_types(store)


def test_J_os_support_suppressed(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "J")
    assert "OS_SUPPORT_ADDED" in live_event_types(store)
    row = store.one(
        """
        SELECT n.disposition FROM notifications n
        JOIN events e ON e.event_key = n.event_key
        WHERE e.event_type = 'OS_SUPPORT_ADDED'
        """
    )
    assert row["disposition"] == "SUPPRESSED"


def test_K_historical_recurrence_creates_transitions(pipeline: Pipeline, store: Store) -> None:
    results = run_scenario(pipeline, "K")
    assert [item.status for item in results] == ["accepted", "accepted", "accepted"]
    hashes = [
        row["content_hash"]
        for row in store.all(
            """
            SELECT content_hash FROM current_entity_observations
            WHERE entity_kind = 'BOARD'
            """
        )
    ]
    assert len(hashes) == 1
    occurrences = store.all(
        "SELECT content_hash FROM observation_occurrences WHERE entity_kind = 'BOARD' ORDER BY occurrence_id"
    )
    assert len(occurrences) == 3
    assert occurrences[0]["content_hash"] == occurrences[2]["content_hash"]
    assert occurrences[0]["content_hash"] != occurrences[1]["content_hash"]
    assert "PORTS_CHANGED" in live_event_types(store)


def test_L_exact_run_replay_is_noop(pipeline: Pipeline, store: Store) -> None:
    first = run_scenario(pipeline, "L")[0]
    second = run_scenario(pipeline, "L")[0]
    assert first.status == "accepted"
    assert second.replayed is True
    assert store.count("processed_run_receipts") == 1
    assert store.count("collector_runs") == 1


def test_M_ambiguous_identity_does_not_auto_merge(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "M")
    assert store.count("socs") == 2
    assert "IDENTITY_ANOMALY" in event_types(store)
    assert store.count("boards") == 1


def test_N_ram_matrix_one_board(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "N")
    assert store.count("boards") == 1
    assert store.count("board_variants") == 3


def test_O_compute_module_matrix(pipeline: Pipeline, store: Store) -> None:
    run_scenario(pipeline, "O")
    assert store.count("boards") == 1
    assert store.count("board_variants") == 6
    board = store.one("SELECT board_type FROM boards")
    assert board["board_type"] == "COMPUTE_MODULE"
