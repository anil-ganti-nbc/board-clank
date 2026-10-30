"""Seven-scope execution fence; excluded parser bodies are never test coverage."""
import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import sys

from sitecustomize import FenceLoader

assert 'board_clank.collectors.raspberry_pi' not in sys.modules, 'RPi fence installed too late'


class RaspberryPiFence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'board_clank.collectors.raspberry_pi':
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            spec.loader = FenceLoader(spec.loader)
            return spec


sys.meta_path.insert(0, RaspberryPiFence())


def pytest_runtest_teardown(item, nextitem):
    assert not Path(os.environ['BOARD_REVIEW_FENCE_LOG']).exists(), 'excluded parser body attempted'
