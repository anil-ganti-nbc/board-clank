"""Separate operational ledger: budgets and durable scheduling/delivery claims."""
from contextlib import contextmanager
from pathlib import Path
import os
import hashlib
import secrets
import sqlite3
import time


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests(source TEXT, at REAL, url_hash TEXT);
                CREATE INDEX IF NOT EXISTS request_window ON requests(source,at);
                CREATE TABLE IF NOT EXISTS source_blocks(source TEXT,permission TEXT,status INTEGER,at REAL,PRIMARY KEY(source,permission));
                CREATE TABLE IF NOT EXISTS source_limits(source TEXT,permission TEXT,next_at REAL,PRIMARY KEY(source,permission));
                CREATE TABLE IF NOT EXISTS cycles(slot TEXT PRIMARY KEY, approval TEXT, status TEXT, started REAL, finished REAL);
                CREATE TABLE IF NOT EXISTS source_runs(slot TEXT,source TEXT,status TEXT,receipt TEXT,PRIMARY KEY(slot,source));
                CREATE TABLE IF NOT EXISTS source_permits(slot TEXT,source TEXT,approval TEXT,token_hash TEXT,owner_pid INTEGER,consumed INTEGER,
                    PRIMARY KEY(slot,source));
                CREATE TABLE IF NOT EXISTS deliveries(destination TEXT,event_key TEXT,status TEXT,attempts INTEGER,next_at REAL,message_id TEXT,
                    PRIMARY KEY(destination,event_key));
                CREATE TABLE IF NOT EXISTS delivery_limits(destination TEXT PRIMARY KEY,next_at REAL);
                CREATE TABLE IF NOT EXISTS delivery_blocks(destination TEXT,permission TEXT,status INTEGER,PRIMARY KEY(destination,permission));
                CREATE TABLE IF NOT EXISTS delivery_confirmations(confirmation TEXT PRIMARY KEY,destination TEXT,credential TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, source, budget, url_hash, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM source_blocks WHERE source=? AND permission=?',
                          (source,budget.access_evidence.sha256)).fetchone():
                raise ValueError('source access denied; new permission evidence required')
            last = db.execute('SELECT MAX(at) FROM requests WHERE source=?', (source,)).fetchone()[0]
            # A backwards clock cannot reset a request budget.
            now = max(now, last or now)
            limit=db.execute('SELECT MAX(next_at) FROM source_limits WHERE source=?',(source,)).fetchone()
            if limit and limit[0] is not None and limit[0]>now:raise ValueError('source server backoff still active')
            hour, day = db.execute('SELECT SUM(at>?),SUM(at>?) FROM requests WHERE source=?',
                                  (now-3600, now-86400, source)).fetchone()
            if (hour or 0) >= budget.max_requests_per_hour or (day or 0) >= budget.max_requests_per_day:
                raise ValueError('source rolling request budget exhausted')
            db.execute('INSERT INTO requests VALUES(?,?,?)', (source, now, url_hash))
        return now

    def block_source(self,source,permission,status):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO source_blocks VALUES(?,?,?,?)',(source,permission,status,time.time()))

    def defer_source(self,source,permission,next_at):
        with self.connect() as db:
            db.execute('INSERT INTO source_limits VALUES(?,?,?) ON CONFLICT(source,permission) DO UPDATE SET next_at=MAX(next_at,excluded.next_at)',
                       (source,permission,next_at))

    def claim_cycle(self, slot, approval):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            exists = db.execute('SELECT status,approval FROM cycles WHERE slot=?', (slot,)).fetchone()
            if exists:
                if exists['approval'] != approval:
                    raise ValueError('approval changed inside existing hour; manual review required')
                return False
            db.execute('INSERT INTO cycles VALUES(?,?,?,?,NULL)', (slot, approval, 'RUNNING', time.time()))
        return True

    def finish_cycle(self, slot, status):
        with self.connect() as db:
            db.execute('UPDATE cycles SET status=?,finished=? WHERE slot=?', (status, time.time(), slot))

    def issue_source(self, slot, source, approval):
        token = secrets.token_hex(32)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cycle = db.execute('SELECT status,approval FROM cycles WHERE slot=?', (slot,)).fetchone()
            if not cycle or cycle['status'] != 'RUNNING' or cycle['approval'] != approval:
                raise ValueError('source permit requires active matching cycle')
            # One attempt per source/hour, including an interrupted subprocess.
            db.execute('INSERT INTO source_permits VALUES(?,?,?,?,?,0)',
                       (slot,source,approval,hashlib.sha256(token.encode()).hexdigest(),os.getpid()))
        return token

    def consume_source(self, slot, source, approval, token, parent_pid):
        if not isinstance(token,str) or len(token)!=64:
            raise ValueError('parent-issued source permit required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cycle=db.execute('SELECT status,approval FROM cycles WHERE slot=?',(slot,)).fetchone()
            permit=db.execute('SELECT * FROM source_permits WHERE slot=? AND source=?',(slot,source)).fetchone()
            if (not cycle or cycle['status']!='RUNNING' or cycle['approval']!=approval
                    or not permit or permit['consumed'] or permit['approval']!=approval
                    or permit['owner_pid']!=parent_pid
                    or not secrets.compare_digest(permit['token_hash'],hashlib.sha256(token.encode()).hexdigest())):
                raise ValueError('source permit absent, stale, consumed or owned by another parent')
            db.execute('UPDATE source_permits SET consumed=1 WHERE slot=? AND source=?',(slot,source))


@contextmanager
def exclusive_lock(path):
    """OS lock; no stale-file deletion and no killing an existing owner."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def assert_running(root):
    root = Path(root)
    if (root/'PAUSED').exists() or (root/'HUMAN_REQUIRED.json').exists():
        raise ValueError('runtime paused or human review required')
