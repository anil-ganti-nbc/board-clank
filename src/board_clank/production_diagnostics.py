"""Read-only export for evidence-backed review; never resolves/suppresses rows."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from board_clank.compatibility import inspect_path
from board_clank.source_profiles import EIGHT_PROFILE, SEVEN_PROFILE, source_scope


def export(db_path,out_path, *, profile_id=EIGHT_PROFILE):
    sources = source_scope(profile_id)
    path=Path(db_path).resolve()
    report=inspect_path(path)
    if str(report.state.value)!='COMPATIBLE':
        raise ValueError('compatible Board schema required; exporter never migrates')
    connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        marks=','.join('?' for _ in sources)
        rows=[dict(r) for r in connection.execute(f"SELECT * FROM diagnostic_conditions WHERE source_key IN ({marks}) ORDER BY source_key,condition_key",sources)]
        last_runs={}
        for source in sources:
            run=connection.execute('SELECT * FROM collector_runs WHERE source_key=? ORDER BY finished_at DESC,run_id DESC LIMIT 1',(source,)).fetchone()
            last_runs[source]=dict(run) if run else None
        counts={}
        for r in rows:
            if r['status']=='OPEN':
                counts[r['diagnostic_type']]=counts.get(r['diagnostic_type'],0)+1
            r['payload_sha256']=hashlib.sha256(r['payload_json'].encode()).hexdigest()
            r['review']={'decision':'UNREVIEWED','rationale':None,'reviewed_by':None,'evidence':None}
        result={'format':1,'observed_utc':datetime.now(timezone.utc).isoformat(),
            'source_database':str(path),'sources':list(sources),'read_only':True,
            'open_counts':counts,'conditions':rows,'source_last_runs':last_runs,
            'meaning':'Conditions preserve uncertainty/conflict; review requires exact payload/state and retained source evidence. No automatic disposition.'}
        with Path(out_path).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,sort_keys=True)
        connection.rollback()
        return {'exported_conditions':len(rows),'open_counts':counts,'state_changed':False}
    finally:connection.close()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--profile',choices=(EIGHT_PROFILE, SEVEN_PROFILE),default=EIGHT_PROFILE)
    args=p.parse_args(argv)
    try:print(json.dumps(export(args.db,args.out,profile_id=args.profile)));return 0
    except Exception as exc:print(json.dumps({'status':'REFUSED','error_type':type(exc).__name__}));return 2


if __name__=='__main__':raise SystemExit(main())
