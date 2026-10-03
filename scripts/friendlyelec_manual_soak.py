"""Operator-invoked three-pass proof in a NEW directory; never a scheduler.

Usage: python scripts/friendlyelec_manual_soak.py --parent <isolated soak parent>
No existing database path is accepted. Never touches a deployed runtime.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

from board_clank.collectors.friendlyelec import FriendlyElecProductAdapter
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    args=parser.parse_args()
    root=Path(tempfile.mkdtemp(prefix='friendlyelec-foundation7a-',dir=args.parent))
    print(json.dumps({'isolated_directory':str(root)}),flush=True)
    store=Store(root/'soak.sqlite')
    sync_sources_to_store(store)
    pipeline=Pipeline(store)
    summaries=[]
    for index in range(1,4):
        now=datetime.now(timezone.utc).isoformat()
        request=FriendlyElecProductAdapter(experimental_live=True).collect(f'friendlyelec-live-{index}',now)
        result=pipeline.accept_run(request)
        counts={table:store.count(table) for table in ('boards','board_families','board_revisions','board_variants','socs','diagnostic_conditions','events','notifications')}
        events=[dict(r) for r in store.all('SELECT event_type,baseline_silent FROM events WHERE run_id=?',(request.run_id,))]
        summary={'pass':index,'at':now,'status':result.status,'baseline':result.baseline,'counts':counts,
                 'event_types':dict(Counter(r['event_type'] for r in events)),
                 'events_added':len(events),'all_new_events_silent':all(r['baseline_silent'] for r in events),
                 'outbox_added':result.notifications,'diagnostics':request.diagnostics,
                 'adapter_sha256':hashlib.sha256(Path(__import__('board_clank.collectors.friendlyelec',fromlist=['x']).__file__).read_bytes()).hexdigest()}
        (root/f'pass-{index}.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        summaries.append({k:v for k,v in summary.items() if k!='diagnostics'})
        print(json.dumps(summaries[-1]),flush=True)
        assert result.status=='accepted', 'live collection failed; evidence preserved'
        assert not store.all("SELECT * FROM notifications WHERE disposition != 'SUPPRESSED'"), 'delivery eligibility forbidden'
        if index==1:
            assert result.baseline and summary['all_new_events_silent']
        else:
            assert len(events)==0 and result.notifications==0, 'semantic churn; evidence preserved'
    integrity=store.one('PRAGMA integrity_check')[0]
    assert integrity=='ok'
    (root/'summary.json').write_text(json.dumps({'passes':summaries,'integrity':integrity},indent=2),encoding='utf-8')
    print(json.dumps({'status':'THREE_PASS_STABLE','evidence':str(root),'integrity':integrity}),flush=True)


if __name__=='__main__':
    main()
