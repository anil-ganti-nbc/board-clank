"""Seven-scope precollection proof; startup owns the one inherited fence."""
import json
import os
from pathlib import Path

from seven_preflight import preflight


def pytest_sessionstart(session):
    # Runs before collection/import of test modules.
    proof = preflight()
    print('Seven guard precollection: ' + json.dumps(proof, sort_keys=True))
    if os.environ.get('BOARD_GUARD_PROOF'):
        Path(os.environ['BOARD_GUARD_PROOF']).write_text(json.dumps(proof, indent=2))



def pytest_runtest_teardown(item, nextitem):
    assert not Path(os.environ['BOARD_REVIEW_FENCE_LOG']).exists(), 'excluded parser body attempted'
