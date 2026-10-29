"""Distinct successor; no historical Hardkernel parser or acquisition exercised."""
import copy
import json

import pytest

from board_clank import eight_source_campaign as campaign
from board_clank.production_policy import SOURCES, MOTHBALLED


def test_hourly_manifest_binds_new_campaign_identity():
    from board_clank.production_runtime import manifest
    value = manifest()
    assert value['campaign_id'] == campaign.load_manifest()['campaign_id']
    assert value['roster_sha256'] == campaign.roster_hash(list(SOURCES))
    assert value['natural_credit'] == 0


def test_versioned_successor_manifest_has_no_inherited_credit():
    manifest = campaign.load_manifest()
    assert manifest['campaign_id'] == 'board-eight-production-v1'
    assert manifest['sources'] == list(SOURCES)
    assert manifest['mothballed'] == [MOTHBALLED]
    assert manifest['natural_credit'] == 0
    assert manifest['acceptance_seconds'] == 604800
    assert manifest['enabled'] is False
    assert manifest['notifications_enabled'] is False
    assert manifest['historical_campaign'] == 'cops-000182-seven-day-d952-r2'
    assert len(campaign.roster_hash(manifest['sources'])) == 64


@pytest.mark.parametrize('kind', ['missing','duplicate','wrong','unknown','mothballed'])
def test_bad_roster_refused(kind):
    value = copy.deepcopy(campaign.load_manifest())
    if kind == 'missing':value['sources'].pop()
    elif kind == 'duplicate':value['sources'][-1] = value['sources'][0]
    elif kind == 'wrong':value['sources'].reverse()
    elif kind == 'unknown':value['sources'][-1] = 'unknown-product'
    else:value['sources'][-1] = MOTHBALLED
    with pytest.raises(ValueError):campaign.validate_manifest(value)


def test_duplicate_contract_keys_refused(tmp_path, monkeypatch):
    path = tmp_path / 'manifest.json'
    raw = campaign.MANIFEST.read_text()
    path.write_text(raw.replace('"format": 1,', '"format": 1, "format": 1,'))
    monkeypatch.setattr(campaign, 'MANIFEST', path)
    with pytest.raises(ValueError, match='duplicate'):
        campaign.load_manifest()


@pytest.mark.parametrize('source', ['unknown-product', MOTHBALLED])
def test_unknown_or_mothballed_refuses_before_lookup(monkeypatch, source):
    monkeypatch.setattr('board_clank.collectors.get_adapter', lambda *a, **kw:pytest.fail('lookup forbidden'))
    with pytest.raises(ValueError):campaign.collect_fixture(source, 'baseline', 'blocked', '2026-10-28T00:00:00Z')


def test_source_failure_cannot_create_qualification(tmp_path, monkeypatch):
    original = campaign.collect_fixture
    def failed(*args):
        request = original(*args)
        request.ok = False
        return request
    monkeypatch.setattr(campaign, 'collect_fixture', failed)
    with pytest.raises(ValueError, match='incomplete'):campaign.qualify(tmp_path/'failed')
    assert not (tmp_path/'failed'/'qualification.json').exists()


def test_existing_root_cli_refusal_preserves_state(tmp_path, capsys):
    marker = tmp_path/'held'
    marker.write_bytes(b'owned state must survive')
    assert campaign.main(['qualify-offline', '--root', str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'REFUSED'
    assert marker.read_bytes() == b'owned state must survive'


def test_mothball_refuses_before_adapter_lookup(monkeypatch):
    monkeypatch.setattr('board_clank.collectors.get_adapter', lambda *a, **kw:pytest.fail('parser dispatch forbidden'))
    with pytest.raises(ValueError, match='mothballed'):
        campaign.collect_fixture(MOTHBALLED, 'baseline', 'blocked', '2026-10-28T00:00:00Z')


def test_offline_campaign_useful_baseline_replay_change_and_recovery(tmp_path):
    root = tmp_path / 'fresh'
    report = campaign.qualify(root)
    assert report['status'] == 'OFFLINE_QUALIFIED'
    assert report['sources'] == list(SOURCES)
    assert report['natural_credit'] == 0
    assert report['production_approval'] is False
    assert report['baseline_silent'] is True
    assert report['unchanged_new_events'] == 0
    assert report['changed_new_events'] > 0
    assert report['restore_equal'] is True
    assert report['restored_replay_new_events'] == 0
    assert report['mothball_asserted'] is True
    assert len(report['baseline']) == 8
    assert all(row['status'] == 'accepted' and row['observations'] > 0 for row in report['baseline'].values())
    assert report == json.loads((root / 'qualification.json').read_text())
    with pytest.raises(ValueError):campaign.qualify(root)
