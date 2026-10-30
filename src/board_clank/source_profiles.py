"""Explicit prospective source profiles; historical eight is never reinterpreted."""
import json
from pathlib import Path
from typing import Literal

ProfileId = Literal['board-eight-production-v1', 'board-seven-production-v1']
EIGHT_PROFILE = 'board-eight-production-v1'
SEVEN_PROFILE = 'board-seven-production-v1'
EIGHT_SOURCES = ('raspberry-pi-product', 'orange-pi-product', 'radxa-product',
                 'banana-pi-product', 'pine64-product', 'friendlyelec-product',
                 'khadas-product', 'forlinx-product')
SEVEN_SOURCES = EIGHT_SOURCES[1:]


def source_scope(profile_id):
    if profile_id == EIGHT_PROFILE:
        return EIGHT_SOURCES
    if profile_id == SEVEN_PROFILE:
        return SEVEN_SOURCES
    raise ValueError('unknown source profile')


def profile_manifest(profile_id=EIGHT_PROFILE):
    from board_clank.eight_source_campaign import load_manifest, _closed_json
    if profile_id == EIGHT_PROFILE:
        return load_manifest()
    source_scope(profile_id)
    path = Path(__file__).with_name('seven-source-campaign.v1.json')
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_closed_json)
    expected = dict(load_manifest(), campaign_id=SEVEN_PROFILE, sources=list(SEVEN_SOURCES),
                    mothballed=['raspberry-pi-product', 'hardkernel-odroid-product'],
                    excluded=['raspberry-pi-product'], predecessor_profile=EIGHT_PROFILE,
                    predecessor_disposition='BLOCKED_SOURCE_POLICY_NO_OPERATIONAL_BASELINE')
    # Canonical JSON equality also distinguishes bools from integers.
    if json.dumps(value, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('seven-source versioned contract differs')
    return value
