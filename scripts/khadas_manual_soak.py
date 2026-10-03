"""Manual three-pass Khadas proof, new isolated DB only; no deployment/scheduler."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

from board_clank.collectors import khadas
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--experimental-live',action='store_true',required=True)
    args=parser.parse_args()
    root=Path(tempfile.mkdtemp(prefix='khadas-foundation8a-',dir=args.parent))
    print(json.dumps({'isolated_directory':str(root)}),flush=True)
    store=Store(root/'soak.sqlite')
    sync_sources_to_store(store)
    pipeline=Pipeline(store)
    summaries=[]
    prior_semantics=None
    for index in range(1,4):
        now=datetime.now(timezone.utc).isoformat()
        request=khadas.KhadasProductAdapter(experimental_live=True).collect(f'khadas-live-{index}',now)
        result=pipeline.accept_run(request)
        counts={table:store.count(table) for table in ('boards','board_families','board_revisions','board_variants','socs','diagnostic_conditions','events','notifications')}
        events=[dict(r) for r in store.all('SELECT event_type,baseline_silent FROM events WHERE run_id=?',(request.run_id,))]
        documents=request.diagnostics['documents']
        semantics={d['page_url']:d.get('semantic_evidence_hash',d['status']) for d in documents}
        summary={'pass':index,'at':now,'status':result.status,'baseline':result.baseline,'counts':counts,
                 'event_types':dict(Counter(r['event_type'] for r in events)),
                 'events_added':len(events),'all_new_events_silent':all(r['baseline_silent'] for r in events),
                 'outbox_added':result.notifications,'diagnostics':request.diagnostics,
                 'document_statuses':dict(Counter(d['status'] for d in documents)),
                 'source_semantics_unchanged':prior_semantics is None or semantics==prior_semantics,
                 'adapter_sha256':hashlib.sha256(Path(khadas.__file__).read_bytes()).hexdigest()}
        (root/f'pass-{index}.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        summaries.append({k:v for k,v in summary.items() if k!='diagnostics'})
        print(json.dumps(summaries[-1]),flush=True)
        assert result.status=='accepted', 'live collection failed; evidence preserved'
        assert not store.all("SELECT * FROM notifications WHERE disposition != 'SUPPRESSED'"), 'delivery eligibility forbidden'
        if index==1:
            assert result.baseline and summary['all_new_events_silent']
        else:
            assert len(events)==0 and result.notifications==0, 'semantic churn; evidence preserved'
            assert semantics==prior_semantics, 'source evidence changed; investigate upstream change'
        prior_semantics=semantics
    integrity=store.one('PRAGMA integrity_check')[0]
    assert integrity=='ok'
    (root/'summary.json').write_text(json.dumps({'passes':summaries,'integrity':integrity},indent=2),encoding='utf-8')
    print(json.dumps({'status':'THREE_PASS_STABLE','evidence':str(root),'integrity':integrity}),flush=True)


if __name__=='__main__':
    main()
