"""Offline qualification of a distinct successor, never runtime admission.

This command only consumes shipped public fixtures. It cannot supply an Approval,
start a clock, enable sources, install a schedule or send notifications.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from board_clank.production_policy import SOURCES, MOTHBALLED

MANIFEST = Path(__file__).with_name('eight-source-campaign.v1.json')


def roster_hash(sources):
    return hashlib.sha256(json.dumps(sources, separators=(',', ':')).encode()).hexdigest()


def validate_manifest(value):
    if value != {
        'format': 1, 'campaign_id': 'board-eight-production-v1',
        'sources': list(SOURCES), 'mothballed': [MOTHBALLED],
        'historical_campaign': 'cops-000182-seven-day-d952-r2',
        'historical_disposition': 'FAILED_NINE_SOURCE_IMMUTABLE',
        'natural_credit': 0, 'acceptance_seconds': 604800, 'cadence_seconds': 3600,
        'enabled': False, 'notifications_enabled': False,
        'clock_origin': 'UNKNOWN_NOT_ACTIVATED',
        'baseline_policy': 'fresh separately authorised production baseline; offline fixtures earn no natural credit',
    }:
        raise ValueError('successor contract differs from versioned eight-source scope')
    # JSON bool/int equivalence must not weaken the literal contract.
    if type(value['format']) is not int or type(value['natural_credit']) is not int:
        raise ValueError('strict integer contract required')
    if value['enabled'] is not False or value['notifications_enabled'] is not False:
        raise ValueError('activation is not supported')
    return value


def _closed_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate campaign key')
        result[key] = value
    return result


def load_manifest():
    return validate_manifest(json.loads(MANIFEST.read_text(encoding='utf-8'), object_pairs_hook=_closed_json))


def collect_fixture(source, corpus, run_id, started_at):
    # Scope guard precedes even adapter lookup: no mothballed parser campaign.
    if source == MOTHBALLED:
        raise ValueError('Hardkernel/ODROID remains mothballed')
    if source not in SOURCES:
        raise ValueError('source outside eight-source successor')
    from board_clank.collectors import get_adapter
    request = get_adapter(source, corpus=corpus).collect(run_id, started_at)
    # Later adapters leave this optional field absent even in corpus mode.
    # Label here at the known fixture-only boundary; never erase provenance.
    if request.fixture_scenario is None:
        request.fixture_scenario = 'eight-offline:' + source + ':' + corpus
    return request


def qualify(root):
    """Fresh fixture-only state; all native facts remain fixture-labelled."""
    from board_clank.backup import create_backup, durable_state_snapshot, restore_backup
    from board_clank.pipeline import Pipeline
    from board_clank.sources import sync_sources_to_store
    from board_clank.store import Store
    manifest = load_manifest()
    root = Path(root).absolute()
    for path in (root, *root.parents):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('linked qualification roots refused')
    if root.exists():
        raise ValueError('fresh exclusively owned qualification root required')
    root.mkdir(mode=0o700, parents=True)
    # Reserve identity before work; failed qualification cannot masquerade as PASS.
    (root/'identity.json').write_text(json.dumps({'scope': 'OFFLINE_FIXTURES_ONLY',
        'campaign': manifest, 'roster_sha256': roster_hash(list(SOURCES))}, indent=2))
    baseline = {}
    with Store(root/'offline.sqlite') as store:
        sync_sources_to_store(store)
        store.execute("UPDATE sources SET enabled=0,promotion_state='MOTHBALLED' WHERE source_key=?", (MOTHBALLED,))
        pipeline = Pipeline(store)
        for source in SOURCES:
            request = collect_fixture(source, 'baseline', 'eight-baseline-'+source, '2026-10-28T00:00:00Z')
            if not request.ok or not request.observations or request.fixture_scenario is None:
                raise ValueError('fixture baseline incomplete')
            result = pipeline.accept_run(request)
            if result.status != 'accepted' or not result.baseline:
                raise ValueError('native baseline not accepted')
            if not pipeline.accept_run(request).replayed:
                raise ValueError('exact receipt replay not idempotent')
            baseline[source] = {'status': result.status, 'observations': len(request.observations),
                'fixture_scenario': request.fixture_scenario, 'run_id': request.run_id,
                'request_sha256': hashlib.sha256(request.model_dump_json().encode()).hexdigest()}
        silent = not store.all('SELECT * FROM events WHERE baseline_silent=0')
        before = store.count('events')
        for source in SOURCES:
            request = collect_fixture(source, 'baseline', 'eight-unchanged-'+source, '2026-10-28T01:00:00Z')
            result = pipeline.accept_run(request)
            if result.status != 'accepted':
                raise ValueError('unchanged fixture rejected')
        unchanged = store.count('events') - before
        before = store.count('events')
        request = collect_fixture(SOURCES[0], 'revision', 'eight-genuine-revision', '2026-10-28T02:00:00Z')
        result = pipeline.accept_run(request)
        changed = store.count('events') - before
        if result.status != 'accepted' or changed <= 0 or unchanged or not silent:
            raise ValueError('baseline/replay/genuine-change invariant failed')
        mothball = store.one('SELECT enabled,promotion_state FROM sources WHERE source_key=?', (MOTHBALLED,))
        if mothball['enabled'] or mothball['promotion_state'] != 'MOTHBALLED':
            raise ValueError('mothball assertion failed')
        if store.all('SELECT * FROM sources WHERE enabled=1'):
            raise ValueError('offline qualification enabled a source')
        # PUSH is a proposed outbox disposition, not delivery. Preserve native
        # classification; no delivery command or sender is invoked here.
        if store.all('SELECT * FROM notifications WHERE delivered_at IS NOT NULL'):
            raise ValueError('offline qualification attempted delivery')
        if store.one('PRAGMA integrity_check')[0] != 'ok' or store.all('PRAGMA foreign_key_check'):
            raise ValueError('offline native integrity failed')
        baselines = [dict(row) for row in store.all('SELECT source_key,baseline_run_id,observation_count FROM source_baselines ORDER BY source_key')]
        if {row['source_key'] for row in baselines} != set(SOURCES):
            raise ValueError('native baseline roster mismatch')
        counts = {table: store.count(table) for table in ('boards','canonical_observations','events','notifications','collector_runs','processed_run_receipts')}
    original = durable_state_snapshot(root/'offline.sqlite')
    backup = create_backup(root/'offline.sqlite', root/'backup')
    recovery = restore_backup(backup.database_path, backup.metadata_path, root/'restored.sqlite', activate=True)
    equal = original == durable_state_snapshot(root/'restored.sqlite')
    if not equal or not recovery['activated']:
        raise ValueError('isolated recovery mismatch')
    with Store(root/'restored.sqlite', migrate=False) as restored:
        before = restored.count('events')
        replay_pipeline = Pipeline(restored)
        # Replay the accepted current RPI revision, not the older baseline
        # (which would be a real A->B->A recurrence, not an unchanged replay).
        for source in SOURCES:
            request = collect_fixture(source, 'revision' if source == SOURCES[0] else 'baseline',
                'eight-restored-'+source, '2026-10-28T03:00:00Z')
            if replay_pipeline.accept_run(request).status != 'accepted':
                raise ValueError('restored replay rejected')
        restored_delta = restored.count('events') - before
        if restored_delta:
            raise ValueError('restored unchanged history created events')
    report = {'status': 'OFFLINE_QUALIFIED', 'campaign_id': manifest['campaign_id'],
        'sources': list(SOURCES), 'roster_sha256': roster_hash(list(SOURCES)),
        'manifest_sha256': hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        'baseline': baseline, 'native_baselines': baselines, 'counts': counts,
        'baseline_silent': silent, 'unchanged_new_events': unchanged,
        'changed_new_events': changed, 'restore_equal': equal, 'restored_replay_new_events': restored_delta, 'mothball_asserted': True,
        'natural_credit': 0, 'production_approval': False, 'clock_origin': 'UNKNOWN_NOT_ACTIVATED',
        'collection_mode': 'SHIPPED_OFFLINE_FIXTURES', 'notifications_enabled': False}
    with (root/'qualification.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('manifest')
    q = sub.add_parser('qualify-offline')
    q.add_argument('--root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = load_manifest() if args.action == 'manifest' else qualify(args.root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'REFUSED', 'error_type': type(exc).__name__,
            'natural_credit': 0, 'production_approval': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
