"""Owner-directed RPi mothball, outside the retained parser implementation."""
from board_clank.collectors.base import CollectorError


def raspberry_pi_hold(original):
    """Keep historical implementation bytes, but never enter acquisition bodies."""
    def refused(*args, **kwargs):
        raise CollectorError('Raspberry Pi mothballed by owner; acquisition and adapter collection disabled')
    return refused
