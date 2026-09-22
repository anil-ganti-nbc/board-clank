from __future__ import annotations

from pathlib import Path

import pytest

from board_clank.fixtures import load_scenario, scenario_to_request
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "board_clank.db"


@pytest.fixture()
def store(db_path: Path) -> Store:
    store = Store(db_path)
    sync_sources_to_store(store)
    return store


@pytest.fixture()
def pipeline(store: Store) -> Pipeline:
    return Pipeline(store)


def run_scenario(pipeline: Pipeline, letter: str):
    payload = load_scenario(letter)
    return [pipeline.accept_run(req) for req in scenario_to_request(payload)]
