"""Prove all admitted adapters from an installed wheel, outside the checkout.

Invoke with python -I so source paths and PYTHONPATH cannot shadow the wheel.
The output/database directory must be fresh and explicitly operator-selected.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()
    assert sys.flags.isolated, 'python -I is required'
    site = args.site.resolve()
    assert site.is_dir() and not args.db.exists(), 'installed site/fresh DB required'
    sys.path.insert(0, str(site))
    import board_clank
    from board_clank.collectors import get_adapter
    from board_clank.manifest import build_manifest, load_manifest, validate_manifest
    from board_clank.pipeline import Pipeline
    from board_clank.sources import assert_foundation_0_roster, sync_sources_to_store
    from board_clank.store import Store
    from board_clank.taxonomy import PHASE1_VENDORS

    imported = Path(board_clank.__file__).resolve()
    assert imported.is_relative_to(site), imported
    assert_foundation_0_roster()
    validate_manifest(build_manifest())
    validate_manifest(load_manifest())
    store = Store(args.db)
    sync_sources_to_store(store)
    pipeline = Pipeline(store)
    results = {}
    for vendor in (*PHASE1_VENDORS, 'friendlyelec', 'khadas', 'forlinx'):
        source = vendor + '-product'
        request = get_adapter(source).collect('installed-wheel-' + vendor, '2026-10-03T00:00:00Z')
        assert request.ok, (source, request.error, request.diagnostics)
        result = pipeline.accept_run(request)
        assert result.status == 'accepted', (source, result.error)
        assert pipeline.accept_run(request).replayed
        results[source] = {'observations': len(request.observations), 'baseline': result.baseline}
    assert len(results) == 9
    assert len(store.all('SELECT DISTINCT vendor_key FROM boards')) == 9
    assert not store.all('SELECT * FROM sources WHERE enabled=1')
    assert not store.all("SELECT * FROM notifications WHERE disposition!='SUPPRESSED'")
    assert store.one('PRAGMA integrity_check')[0] == 'ok'
    assert not store.all('PRAGMA foreign_key_check')
    print(json.dumps({'module_path': str(imported), 'sources': results,
        'boards': store.count('boards'), 'schema': 3, 'integrity': 'ok'}, indent=2))
    store.close()


if __name__ == '__main__':
    main()
