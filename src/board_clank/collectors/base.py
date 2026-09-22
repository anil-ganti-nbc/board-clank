from __future__ import annotations
from abc import ABC, abstractmethod
from board_clank.models import CollectorRunRequest, ObservationDraft
class CollectorError(RuntimeError):
    pass
class CollectorAdapter(ABC):
    live_network = False
    @abstractmethod
    def collect(self, run_id: str, started_at: str) -> CollectorRunRequest:
        raise NotImplementedError
