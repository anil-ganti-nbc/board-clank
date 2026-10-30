"""Explicit, revision-bound production admission; never an automatic promotion."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from board_clank.source_profiles import EIGHT_SOURCES as SOURCES, EIGHT_PROFILE, ProfileId, source_scope
MOTHBALLED = 'hardkernel-odroid-product'
HOSTS = {
    SOURCES[0]: {'pip.raspberrypi.com', 'pip-assets.raspberrypi.com', 'www.raspberrypi.com'},
    SOURCES[1]: {'www.orangepi.org'}, SOURCES[2]: {'radxa.com'},
    SOURCES[3]: {'banana-pi.org'}, SOURCES[4]: {'pine64.org'},
    SOURCES[5]: {'www.friendlyelec.com'}, SOURCES[6]: {'www.khadas.com'},
    SOURCES[7]: {'www.forlinx.net'},
}
GATES = {'source_access', 'diagnostics', 'integrity', 'replay', 'backup_restore',
         'tests', 'locked_ci', 'container', 'independent_review', 'schedule_rollback'}


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def code_digest() -> str:
    """Bind approval to installed code bytes, including packaged registry/schema."""
    root = Path(__file__).parent
    rows = [(p.relative_to(root).as_posix(), digest(p.read_bytes()))
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
            and p.suffix not in {'.pyc', '.pyo'}]
    from board_clank.sources import DEFAULT_SOURCES_PATH
    rows.append(('effective_source_registry',digest(Path(DEFAULT_SOURCES_PATH).read_bytes())))
    return digest(json.dumps(rows, separators=(',', ':')).encode())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Evidence(StrictModel):
    path: str
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    def read(self, root: Path) -> bytes:
        rel = Path(self.path)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise ValueError('evidence must stay inside approval directory')
        p = root.joinpath(rel)
        # Reject symlinks at every component, including Windows junctions.
        for part in (p, *p.parents):
            if part == root.parent:
                break
            if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
                raise ValueError('linked evidence refused')
        if not p.resolve().is_relative_to(root.resolve()) or p.stat().st_size > 8_000_000:
            raise ValueError('evidence boundary refused')
        raw = p.read_bytes()
        if digest(raw) != self.sha256:
            raise ValueError('evidence hash changed')
        return raw


class SourceBudget(StrictModel):
    origins: tuple[str, ...]
    max_requests_per_cycle: StrictInt = Field(ge=1, le=1000)
    max_requests_per_hour: StrictInt = Field(ge=1, le=1000)
    max_requests_per_day: StrictInt = Field(ge=1, le=24000)
    max_concurrency: StrictInt = Field(ge=1,le=4)
    min_interval_seconds: float = Field(ge=0, le=600, allow_inf_nan=False)
    timeout_seconds: StrictInt = Field(ge=1, le=60)
    cycle_timeout_seconds: StrictInt = Field(ge=1, le=1800)
    max_response_bytes: StrictInt = Field(ge=1, le=8_000_000)
    max_total_response_bytes: StrictInt = Field(ge=1, le=256_000_000)
    allow_missing_robots: StrictBool = False
    retries: StrictInt = Field(ge=0, le=2)
    access_evidence: Evidence

    @model_validator(mode='after')
    def bounds(self):
        if not self.origins or len(set(self.origins)) != len(self.origins):
            raise ValueError('unique nonempty origins required')
        if (self.max_requests_per_hour < self.max_requests_per_cycle
                or self.max_requests_per_day < 24*self.max_requests_per_cycle
                or self.timeout_seconds > self.cycle_timeout_seconds):
            raise ValueError('budget cannot support declared hourly cadence')
        return self


class Disposition(StrictModel):
    condition_key: str
    source_key: str
    state_hash: str
    payload_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: str = Field(pattern=r'^(accepted_uncertainty|excluded_coverage|fixed_by_replay)$')
    rationale: str = Field(min_length=20)
    reviewed_by: str = Field(min_length=1)
    evidence: Evidence


class Approval(StrictModel):
    format: StrictInt = 1
    profile_id: ProfileId = EIGHT_PROFILE
    revision: str = Field(pattern=r'^[a-f0-9]{40}$')
    code_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    approved_by: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    approved_at: str
    expires_at: str
    source_budgets: dict[str, SourceBudget]
    gates: dict[str, Evidence]
    dispositions: tuple[Disposition, ...] = ()
    campaign: Evidence | None = None

    @property
    def sources(self):
        return source_scope(self.profile_id)

    def validate_current(self, root: Path, revision: str, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if self.format != 1 or self.revision != revision or self.code_sha256 != code_digest():
            raise ValueError('candidate identity changed or unverified')
        if self.campaign is not None:
            from board_clank.campaign_acceptance import campaign_spec
            campaign_spec(self, root)
        start, end = utc(self.approved_at), utc(self.expires_at)
        if not start <= now < end:
            raise ValueError('approval expired or future-dated')
        sources = self.sources
        if set(self.source_budgets) != set(sources) or set(self.gates) != GATES:
            raise ValueError('exact versioned source scope and all gates required')
        if sum(b.cycle_timeout_seconds for b in self.source_budgets.values()) > 3300:
            raise ValueError('aggregate source deadlines exceed hourly envelope')
        for source, budget in self.source_budgets.items():
            for origin in budget.origins:
                p = urlsplit(origin)
                if (p.scheme not in {'https', 'http'} or p.netloc not in HOSTS[source]
                        or p.path or p.query or p.fragment):
                    raise ValueError('origin outside existing source scope')
            access = json.loads(budget.access_evidence.read(root))
            if (access.get('source') != source or access.get('approved_budget') != budget.model_dump(mode='json',exclude={'access_evidence'})
                    or not access.get('permission_basis') or utc(access['valid_until']) < end):
                raise ValueError('source permission/budget evidence incomplete')
        for gate, ref in self.gates.items():
            proof = json.loads(ref.read(root))
            if (proof.get('gate') != gate or proof.get('revision') != revision
                    or proof.get('code_sha256') != self.code_sha256 or proof.get('status') != 'PASS'
                    or not proof.get('reviewed_by') or not proof.get('evidence_references')):
                raise ValueError('unverified production gate: '+gate)
        keys = [d.condition_key for d in self.dispositions]
        if len(keys) != len(set(keys)) or any(d.source_key not in sources for d in self.dispositions):
            raise ValueError('duplicate or out-of-scope diagnostic disposition')
        for d in self.dispositions:
            raw=d.evidence.read(root)
            if d.decision=='fixed_by_replay':
                fix=json.loads(raw)
                if (fix.get('revision')!=revision or fix.get('code_sha256')!=self.code_sha256
                        or fix.get('condition_key')!=d.condition_key or fix.get('old_state_hash')!=d.state_hash
                        or fix.get('status')!='RESOLVED_BY_REPLAY' or not fix.get('reviewed_by')):
                    raise ValueError('fixed diagnostic lacks exact-candidate replay proof')
                qualified=json.loads(Evidence.model_validate(fix['qualification_snapshot']).read(root))
                last=qualified.get('source_last_runs',{}).get(d.source_key) or {}
                if (qualified.get('read_only') is not True or qualified.get('sources')!=list(sources)
                        or last.get('status')!='accepted' or last.get('source_key')!=d.source_key
                        or not last.get('run_id') or 'fixture_scenario' not in last or last['fixture_scenario'] is not None
                        or any(row['condition_key']==d.condition_key and row['status']=='OPEN'
                               for row in qualified['conditions'])):
                    raise ValueError('fixed diagnostic remains open or source replay is incomplete')
                if not fix.get('source_captures'):raise ValueError('retained source capture references required')
                for capture in fix['source_captures']:Evidence.model_validate(capture).read(root)
        diagnostic_proof=json.loads(self.gates['diagnostics'].read(root))
        snapshot=json.loads(Evidence.model_validate(diagnostic_proof['diagnostic_snapshot']).read(root))
        if snapshot.get('sources')!=list(sources) or snapshot.get('read_only') is not True:
            raise ValueError('diagnostic snapshot scope/provenance incomplete')
        condition_keys=[row['condition_key'] for row in snapshot['conditions']]
        if len(condition_keys)!=len(set(condition_keys)):raise ValueError('duplicate snapshot diagnostic condition')
        reviewed={d.condition_key:d for d in self.dispositions}
        for row in snapshot['conditions']:
            if row['source_key'] not in sources:raise ValueError('snapshot source scope widened')
            if row['status'] not in {'OPEN','RESOLVED'}:raise ValueError('unknown snapshot diagnostic state')
            if row['status']=='OPEN':
                d=reviewed.get(row['condition_key'])
                if (not d or d.source_key!=row['source_key'] or d.state_hash!=row['state_hash']
                        or d.payload_sha256!=digest(row['payload_json'].encode())):
                    raise ValueError('historical diagnostic condition lacks evidence-bound disposition')


class Admission:
    """Loaded file is revalidated before every admission; changes fail closed."""
    def __init__(self, path: Path, revision: str):
        self.path = path.resolve()
        self.revision = revision
        self.raw_hash = digest(self.path.read_bytes())
        self.approval = Approval.model_validate_json(self.path.read_bytes())
        self.validate()

    def validate(self):
        raw=self.path.read_bytes()
        if digest(raw) != self.raw_hash:
            raise ValueError('approval file changed')
        if Approval.model_validate_json(raw).model_dump()!=self.approval.model_dump():
            raise ValueError('in-memory approval state changed')
        self.approval.validate_current(self.path.parent, self.revision)

    @property
    def sources(self):
        return self.approval.sources

    def authorize(self, source: str):
        self.validate()
        if source not in self.sources:
            raise ValueError('source not approved; ODROID remains mothballed')

    def check_diagnostics(self, store):
        self.validate()
        reviewed = {d.condition_key: d for d in self.approval.dispositions}
        placeholders = ','.join('?' for _ in self.sources)
        rows = store.all(f"SELECT * FROM diagnostic_conditions WHERE source_key IN ({placeholders})", self.sources)
        for row in rows:
            if row['status'] not in {'OPEN','RESOLVED'}:raise ValueError('unknown current diagnostic state')
            if row['status']=='RESOLVED':continue
            d = reviewed.get(row['condition_key'])
            if (not d or d.decision=='fixed_by_replay' or d.source_key != row['source_key'] or d.state_hash != row['state_hash']
                    or d.payload_sha256 != digest(row['payload_json'].encode())):
                raise ValueError('undispositioned or changed diagnostic condition')


def validate_state(store, admission):
    """Refuse global state faults before acquisition or delivery."""
    if store.one('PRAGMA integrity_check')[0]!='ok' or store.all('PRAGMA foreign_key_check'):
        raise ValueError('production state integrity failure')
    validate_registry(store, admission.sources)
    admission.check_diagnostics(store)


def validate_registry(store, sources=SOURCES):
    """Shared durable scope/provenance check, including before acquisition."""
    from board_clank.sources import load_sources
    declared = {r.source_key: r for r in load_sources()}
    mothballed = store.one('SELECT enabled,promotion_state FROM sources WHERE source_key=?', (MOTHBALLED,))
    if not mothballed or mothballed['enabled'] or mothballed['promotion_state'] != 'MOTHBALLED':
        raise ValueError('ODROID mothball state drift')
    if SOURCES[0] not in sources:
        excluded = store.one('SELECT enabled,promotion_state FROM sources WHERE source_key=?', (SOURCES[0],))
        if not excluded or excluded['enabled'] or excluded['promotion_state'] != 'MOTHBALLED':
            raise ValueError('Raspberry Pi mothball state drift')
    enabled = store.all('SELECT source_key FROM sources WHERE enabled!=0')
    if {row['source_key'] for row in enabled} != set(sources):
        raise ValueError('production source scope drift')
    for source in sources:
        trusted = declared[source].model_copy(update={'enabled': True, 'promotion_state': 'PROMOTED'})
        row = store.one('SELECT * FROM sources WHERE source_key=?', (source,))
        if (trusted.registered_state != 'REGISTERED' or trusted.placeholder or trusted.out_of_scope
                or trusted.plane != 'PRODUCT' or trusted.authority != 'FIRST_PARTY_CANONICAL'
                or row is None or any(row[key] != getattr(trusted, key)
                    for key in ('vendor', 'plane', 'authority', 'registered_state', 'enabled',
                                'promotion_state', 'placeholder', 'out_of_scope'))):
            raise ValueError('durable source provenance differs from trusted registry')


def promote_registry(store, admission: Admission):
    """An explicit transition, called only for a separately initialized production DB."""
    admission.check_diagnostics(store)
    from board_clank.sources import load_sources
    declared = {r.source_key: r for r in load_sources()}
    store.begin()
    try:
        for source in admission.sources:
            trusted = declared[source]
            row = store.one('SELECT * FROM sources WHERE source_key=?', (source,))
            if not row or trusted.placeholder or trusted.out_of_scope or row['vendor'] != trusted.vendor:
                raise ValueError('production registry identity mismatch')
            store.execute("UPDATE sources SET enabled=1,promotion_state='PROMOTED' WHERE source_key=?", (source,))
        store.execute("UPDATE sources SET enabled=0,promotion_state='MOTHBALLED' WHERE source_key=?", (MOTHBALLED,))
        if SOURCES[0] not in admission.sources:
            store.execute("UPDATE sources SET enabled=0,promotion_state='MOTHBALLED' WHERE source_key=?", (SOURCES[0],))
        store.commit()
    except Exception:
        store.rollback()
        raise
