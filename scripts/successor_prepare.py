"""Compose existing native init + verified staging restore; no collection/arming.
Default is read-only preflight. Run only on a new reviewed successor namespace.
The transient empty init image is replaced before any producer can run.
"""
import argparse, hashlib, json, os, shutil, sqlite3
from contextlib import closing
from pathlib import Path
from board_clank.backup import restore_backup, verify_backup
from board_clank.production_policy import Admission, validate_state
from board_clank.production_runtime import initialize, immutable
from board_clank.production_ledger import exclusive_lock
from board_clank.store import Store
from board_clank._version import SOURCE_REVISION


def prepare(root, approval, packet, write=False):
    root, packet = Path(root).absolute(), Path(packet).resolve()
    manifest = json.loads((packet / 'recovery-manifest.json').read_text())
    admission = Admission(Path(approval), SOURCE_REVISION)
    if root.exists():
        raise ValueError('successor must be a distinct absent namespace')
    for rel, expected in manifest['files'].items():
        p = packet / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise ValueError('invalid packet path')
        if any(q.is_symlink() or (hasattr(q, 'is_junction') and q.is_junction())
               for q in [p, *p.parents] if q != packet.parent):
            raise ValueError('linked packet refused')
        if p.stat().st_size != expected['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('recovery input drift')
    domain = packet / manifest['domain']
    meta = packet / manifest['domain_meta']
    ops = packet / manifest['operations']
    verify_backup(domain, meta)
    with closing(sqlite3.connect(ops.as_uri() + '?mode=ro', uri=True)) as c:
        assert c.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert c.execute('select count(*) from requests').fetchone()[0] == manifest['charged_requests'] == 92
        assert c.execute('select status from cycles where slot=?', (manifest['failed_slot'],)).fetchone()[0] == 'HUMAN_REQUIRED'
    stage = admission.initialization_spec(root) if admission.approval.initialization is not None else None
    if stage:
        if (stage.recovery_sha256 != hashlib.sha256((packet/'recovery-manifest.json').read_bytes()).hexdigest()
                or stage.predecessor_slot != manifest['failed_slot']
                or stage.charged_requests != manifest['charged_requests']):
            raise ValueError('initialization admission binds another recovery packet')
        prior = json.loads((packet/'predecessor/approval/approval.json').read_bytes())
        from board_clank.production_policy import utc
        if utc(prior['expires_at']) != utc(stage.expires_at):
            raise ValueError('successor must preserve predecessor absolute expiry; no lease extension')
        for source in admission.sources:
            old = {k: v for k, v in prior['source_budgets'][source].items() if k != 'access_evidence'}
            if old != admission.approval.source_budgets[source].model_dump(mode='json', exclude={'access_evidence'}):
                raise ValueError('successor must preserve source/publisher budget caps')
    report = {'status': 'READ_ONLY_PREFLIGHT', 'root': str(root), 'requests_retained': 92,
              'quota_refund': 0, 'collection_invoked': False, 't0': None,
              'remaining_cycle_reservations': stage.aggregate_reservations-stage.predecessor_consumed if stage else 168,
              'aggregate_cycle_reservations': stage.aggregate_reservations if stage else 169,
              'future_hourly_slots': stage.future_slots if stage else 168,
              'initialization_authority': admission.approval.initialization.model_dump() if stage else None,
              'old_failed_slot_preserved': True}
    if not write:
        return report
    # This supported initializer binds a *new* campaign; no old grant is rewritten.
    # No producer runs while replacing its freshly created empty staging image.
    initialize(root, admission)
    immutable(root / 'PAUSED', {'reason': 'prepared successor; separate reviewed activation required'})
    with exclusive_lock(root / 'runtime.lock'):
        with closing(sqlite3.connect((root / 'board.sqlite').as_uri() + '?mode=ro', uri=True)) as c:
            assert c.execute('select count(*) from boards').fetchone()[0] == 0
        restore_backup(domain, meta, root / 'board.sqlite', activate=True, force=True)
        with closing(sqlite3.connect(ops.as_uri() + '?mode=ro', uri=True)) as a:
            with closing(sqlite3.connect(root / 'operations.sqlite')) as b:
                a.backup(b)
        for rel in manifest['history']:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as f:
                f.write((packet / rel).read_bytes())
                f.flush(); os.fsync(f.fileno())
        store = Store(root / 'board.sqlite', migrate=False)
        try:
            validate_state(store, admission)
            assert store.count('boards') >= 25 and store.count('canonical_observations') >= 235
            report.update(status='PREPARED_PAUSED', boards=store.count('boards'),
                          observations=store.count('canonical_observations'))
        finally:
            store.close()
        immutable(root / 'state-preserving-recovery.json', dict(report, input_manifest_sha256=
            hashlib.sha256((packet / 'recovery-manifest.json').read_bytes()).hexdigest(),
            approval_sha256=admission.raw_hash, historical_credit=0))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--approval', required=True)
    p.add_argument('--packet', required=True)
    p.add_argument('--write', action='store_true')
    args = p.parse_args()
    print(json.dumps(prepare(args.root, args.approval, args.packet, args.write), indent=2))
