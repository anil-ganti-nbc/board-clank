"""One manually invoked experimental pass; execute separately with --pass 1, 2, 3.

Pass 1 creates a new isolated directory/DB. Later passes require its predecessor.
Raw HTTP bytes and normalized requests are retained. No enablement or deployment.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from board_clank.backup import create_backup, durable_state_snapshot, restore_backup
from board_clank.collectors import forlinx
from board_clank.observer import full_snapshot
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--pass', dest='ordinal', type=int, choices=(1, 2, 3), required=True)
    parser.add_argument('--experimental-live', action='store_true', required=True)
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    if args.ordinal == 1:
        root.mkdir(parents=True, exist_ok=False)
    else:
        assert (root / f'pass-{args.ordinal - 1}.json').exists(), 'previous accepted pass required'
    pass_dir = root / f'pass-{args.ordinal}'
    pass_dir.mkdir(exist_ok=False)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip(), 'live qualification requires frozen clean candidate'
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    original = forlinx.fetch

    def capture(url):
        result = original(url)
        target = pass_dir / (url.rsplit('/', 1)[-1] + '.raw.html')
        target.write_bytes(result['raw_body'])
        (pass_dir / (target.name + '.json')).write_text(json.dumps({
            k: v for k, v in result.items() if k not in ('text', 'raw_body')}, indent=2), encoding='utf-8')
        return result

    forlinx.fetch = capture
    now = datetime.now(timezone.utc).isoformat()
    db = root / 'isolated-soak.sqlite'
    assert args.ordinal != 1 or not db.exists(), 'first pass must use a fresh DB'
    store = Store(db)
    sync_sources_to_store(store)
    pipeline = Pipeline(store)
    request = forlinx.ForlinxProductAdapter(experimental_live=True).collect(f'forlinx-live-{args.ordinal}', now)
    (pass_dir / 'request.json').write_text(request.model_dump_json(indent=2), encoding='utf-8')
    result = pipeline.accept_run(request)
    events = [dict(r) for r in store.all('SELECT event_type,baseline_silent FROM events WHERE run_id=?', (request.run_id,))]
    semantics = {d['page_url']: d.get('semantic_evidence_hash', d['status']) for d in request.diagnostics['documents']}
    summary = {'pass': args.ordinal, 'at': now, 'execution_sha': revision, 'execution_tree': tree,
        'adapter_sha256': hashlib.sha256(Path(forlinx.__file__).read_bytes()).hexdigest(),
        'status': result.status, 'baseline': result.baseline, 'counts': {t: store.count(t) for t in (
            'boards', 'board_families', 'board_revisions', 'board_variants', 'socs', 'diagnostic_conditions',
            'diagnostic_sightings', 'events', 'notifications', 'collector_runs', 'processed_run_receipts')},
        'events_added': len(events), 'outbox_added': result.notifications,
        'event_types': dict(Counter(e['event_type'] for e in events)),
        'all_new_events_silent': all(e['baseline_silent'] for e in events),
        'document_statuses': dict(Counter(d['status'] for d in request.diagnostics['documents'])),
        'fetch_count': len(request.diagnostics['fetches']), 'diagnostics': request.diagnostics,
        'semantic_hashes': semantics, 'integrity': store.one('PRAGMA integrity_check')[0],
        'foreign_key_check': [dict(r) for r in store.all('PRAGMA foreign_key_check')]}
    (root / f'pass-{args.ordinal}.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('diagnostics', 'semantic_hashes')}, indent=2), flush=True)
    assert result.status == 'accepted', 'live collection failed; raw evidence preserved'
    assert summary['integrity'] == 'ok' and not summary['foreign_key_check']
    assert not store.all("SELECT * FROM notifications WHERE disposition != 'SUPPRESSED'")
    assert not store.all('SELECT * FROM sources WHERE enabled=1 OR promotion_state=\'PROMOTED\'')
    if args.ordinal == 1:
        assert result.baseline and summary['all_new_events_silent']
    else:
        prior = json.loads((root / f'pass-{args.ordinal - 1}.json').read_text(encoding='utf-8'))
        assert semantics == prior['semantic_hashes'], 'upstream semantic change requires investigation'
        assert not events and result.notifications == 0, 'false replay churn'
    before = durable_state_snapshot(db)
    assert pipeline.accept_run(request).replayed
    assert durable_state_snapshot(db) == before
    if args.ordinal == 3:
        store.close()
        observer_before = hashlib.sha256(db.read_bytes()).hexdigest()
        observer = full_snapshot(db)
        assert hashlib.sha256(db.read_bytes()).hexdigest() == observer_before
        (root / 'observer.json').write_text(json.dumps(observer, indent=2), encoding='utf-8')
        backup = create_backup(db, root / 'backup')
        restored = root / 'restored.sqlite'
        restore_backup(backup.database_path, backup.metadata_path, restored, activate=True)
        assert durable_state_snapshot(restored) == durable_state_snapshot(db)
        replay_store = Store(restored)
        assert Pipeline(replay_store).accept_run(request).replayed
        later = request.model_copy(deep=True)
        later.run_id = 'forlinx-restored-new-run'
        replay = Pipeline(replay_store).accept_run(later)
        assert replay.status == 'accepted' and replay.events == [] and replay.notifications == 0
        replay_store.close()
        (root / 'readiness.json').write_text(json.dumps({'observer_read_only': True, 'schema': 3,
            'backup': str(backup.database_path), 'backup_sha256': backup.sha256,
            'restored_receipt_replay': True, 'restored_new_run_noop': True}, indent=2), encoding='utf-8')
    print('FORLINX_MANUAL_PASS_ACCEPTED', args.ordinal, flush=True)


if __name__ == '__main__':
    main()
