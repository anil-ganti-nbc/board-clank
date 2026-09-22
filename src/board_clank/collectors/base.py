from __future__ import annotations

from abc import ABC, abstractmethod

from board_clank.models import CollectorRunRequest, ObservationDraft


class CollectorError(RuntimeError):
    pass


class CollectorAdapter(ABC):
    source_key: str
    collector_key: str
    live_network = False

    @abstractmethod
    def collect(self, run_id: str, started_at: str) -> CollectorRunRequest:
        raise NotImplementedError

    def parse_fixture(self, payload: dict) -> list[ObservationDraft]:
        raise CollectorError("this adapter does not parse live documents in Foundation 0")
