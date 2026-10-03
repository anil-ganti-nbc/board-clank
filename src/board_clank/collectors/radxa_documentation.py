"""Manual, bounded ROCK 5B hardware-reference POC. Never admits PRODUCT drafts.

References have their own typed namespace in schema v3. They link to an
existing validated PRODUCT Board and cannot change its graph/current/novelty.
See docs/EVIDENCE_PLANE_ARCHITECTURE.md for the semantic contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from board_clank._version import SOURCE_REVISION
from board_clank.collectors.base import CollectorError
from board_clank.identity import UNKNOWN, board_key
from board_clank.models import EventRecord, SourceRecord, canonical_json, content_hash
from board_clank.sources import load_sources, sync_sources_to_store
from board_clank.store import Store
from board_clank.taxonomy import BoardType, EntityKind, EventType, SourceAuthority, SourcePlane

SOURCE_KEY = "radxa-rock5b-documentation-poc"
DOCS_URL = "https://docs.radxa.com/en/rock5/rock5b/download"
PRODUCT_URL = "https://radxa.com/products/rock5/5b/"
MODEL = "ROCK 5B"
ARTIFACT_PREFIX = "/rock5/5b/docs/hw/"
KIND = EntityKind.DOCUMENTATION_REFERENCE.value
_REVISION = re.compile(r"^V(\d+\.\d+)(?:\b|\s|\()", re.I)
_FIXTURE = Path(__file__).resolve().parents[1] / "fixture_data/radxa_documentation/rock5b-hardware.html"


def _text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).replace("\u200b", "")).strip()


def _url(url: str, *, artifact: bool = False, product: bool = False) -> str:
    """Strict first-party policy; cosmetic fragments/download=1 are normalized.

    Reject encoded path separators/traversal, credentials, ports, lookalike
    hosts and unknown queries rather than accepting them as aliases.
    """
    if any(ord(c) < 33 for c in url) or "\\" in url:
        raise CollectorError("unsafe URL characters")
    try:
        p = urlsplit(url)
    except ValueError as e:
        raise CollectorError("malformed URL") from e
    host = "dl.radxa.com" if artifact else ("radxa.com" if product else "docs.radxa.com")
    if p.scheme != "https" or p.netloc.lower() != host or "%" in p.path:
        raise CollectorError("URL is outside the bounded first-party surface")
    if any(part in {".", "..", ""} for part in p.path.split("/")[1:-1]):
        raise CollectorError("ambiguous URL path")
    if artifact:
        if not p.path.startswith(ARTIFACT_PREFIX) or not p.path.rsplit("/", 1)[-1]:
            raise CollectorError("artifact belongs to another model or section")
        if any(k != "download" or v != "1" for k, v in parse_qsl(p.query, keep_blank_values=True)):
            raise CollectorError("unverified artifact query")
    else:
        expected = PRODUCT_URL if product else DOCS_URL
        if p.query or p.path.rstrip("/") != urlsplit(expected).path.rstrip("/"):
            raise CollectorError("URL is not the exact bounded page")
    return urlunsplit(("https", host, p.path.rstrip("/") if not artifact else p.path, "", ""))


@dataclass
class RevisionReference:
    hardware_label: str
    notes: str
    artifacts: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "relationship": "REFERENCE_TO_BOARD", "vendor_key": "radxa", "model": MODEL,
            "plane": SourcePlane.DOCUMENTATION.value, "page_url": DOCS_URL,
            "section": "Hardware Design", "hardware_revision_label": self.hardware_label,
            "notes": _text(self.notes).casefold(), "artifact_urls": sorted(set(self.artifacts)),
            "document_revision": UNKNOWN, "effective_at": UNKNOWN,
            "market_novelty": False, "authority": SourceAuthority.FIRST_PARTY_SUPPORTING.value,
        }


class _HardwareParser(HTMLParser):
    """Read one explicit tab panel; the rest of the page never supplies claims.

    Docusaurus output omits li/p end tags. Div depth, h3 boundaries and tab
    labels are used explicitly; this parser does not depend on balanced li.
    """
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.active = False
        self.sections = 0
        self.labels: list[str] = []
        self.tab_text: list[str] | None = None
        self.div_depth = 0
        self.panel_depth: int | None = None
        self.panel_count = 0
        self.panel_selected = False
        self.heading: list[str] | None = None
        self.claim: RevisionReference | None = None
        self.claims: list[RevisionReference] = []
        self.panel_artifacts: list[str] = []
        self.errors: list[str] = []
        self.ignored_models: list[str] = []
        self.hidden = 0
        self.artifact_anchor = False

    def _flush_tab(self) -> None:
        if self.tab_text is not None:
            self.labels.append(_text(" ".join(self.tab_text)))
            self.tab_text = None

    def _flush_claim(self) -> None:
        if self.claim is not None:
            self.claim.notes = _text(self.claim.notes)
            self.claim.artifacts = sorted(set(self.claim.artifacts))
            self.claims.append(self.claim)
            self.claim = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "h2":
            self._flush_claim()
            self.active = a.get("id") == "hardware-design"
            if self.active:
                self.sections += 1
        if tag == "div":
            self.div_depth += 1
            if self.active and a.get("role") == "tabpanel":
                self._flush_tab()
                if self.panel_depth is not None:
                    self.errors.append("nested hardware tab panels")
                self.panel_depth = self.div_depth
                self.panel_count += 1
                label = self.labels[self.panel_count - 1] if self.panel_count <= len(self.labels) else UNKNOWN
                self.panel_selected = label == MODEL
                if not self.panel_selected:
                    self.ignored_models.append(label)
        if not self.active:
            return
        if tag == "li" and a.get("role") == "tab":
            self._flush_tab()
            self.tab_text = []
        if self.panel_selected and tag == "h3":
            self._flush_claim()
            self.heading = []
        if self.panel_selected and tag == "a" and a.get("href"):
            href = a["href"]
            if href.startswith("#"):
                return
            try:
                target = _url(urljoin(DOCS_URL, href), artifact=True)
            except CollectorError as e:
                self.errors.append(str(e))
                return
            self.panel_artifacts.append(target)
            self.artifact_anchor = True
            if self.claim is not None:
                self.claim.artifacts.append(target)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.artifact_anchor = False
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"li", "ul"}:
            self._flush_tab()
        if tag == "h3" and self.heading is not None:
            title = _text(" ".join(self.heading))
            m = _REVISION.match(title)
            if not m:
                self.errors.append("hardware heading has no explicit revision label")
            else:
                self.claim = RevisionReference("V" + m.group(1), title[m.end():].strip(), [])
            self.heading = None
        if tag == "div":
            if self.panel_depth == self.div_depth:
                self._flush_claim()
                self.panel_depth = None
                self.panel_selected = False
            self.div_depth = max(0, self.div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        if self.tab_text is not None:
            self.tab_text.append(data)
        elif self.heading is not None:
            self.heading.append(data)
        elif self.active and self.panel_selected and self.claim is not None and not self.artifact_anchor:
            self.claim.notes += " " + data


def parse_hardware(html: str, *, page_url: str = DOCS_URL) -> tuple[list[RevisionReference], dict]:
    _url(page_url)
    p = _HardwareParser()
    p.feed(html)
    p.close()
    # Do not flush an unfinished panel: truncated documents fail closed.
    if p.sections != 1 or p.labels.count(MODEL) != 1 or p.panel_count != len(p.labels):
        p.errors.append("missing or ambiguous model/section/tab structure")
    if p.panel_depth is not None or p.heading is not None:
        p.errors.append("truncated hardware panel")
    if not p.panel_artifacts:
        p.errors.append("missing first-party model-bearing artifact crosslinks")
    labels = [c.hardware_label for c in p.claims]
    if not labels or len(labels) != len(set(labels)):
        p.errors.append("missing or duplicate hardware revision labels")
    claims = [] if p.errors else p.claims
    info = {
        "page_url": DOCS_URL, "status": "unresolved" if p.errors else "parsed",
        "model": MODEL, "errors": sorted(set(p.errors)), "ignored_models": p.ignored_models,
        "artifact_crosslinks": sorted(set(p.panel_artifacts)),
        "semantic_hash": content_hash([c.payload() for c in sorted(claims, key=lambda c: c.hardware_label)]),
        "raw_body_hash": hashlib.sha256(html.encode("utf-8")).hexdigest(),
    }
    return claims, info


def source_definition() -> SourceRecord:
    return SourceRecord(
        source_key=SOURCE_KEY, vendor="radxa", plane=SourcePlane.DOCUMENTATION,
        authority=SourceAuthority.FIRST_PARTY_SUPPORTING, base_urls=[DOCS_URL],
        enabled=False, promotion_state="EXPERIMENTAL", registered_state="REGISTERED",
        expected_identity_surface="REFERENCE_TO_BOARD; explicit model + official artifact path + existing PRODUCT",
        expected_variant_surface="NONE", notes="Isolated manual ROCK 5B POC; supporting history only; no promotion/delivery.",
    )


def _source_from_row(row) -> SourceRecord:
    data = dict(row)
    data["base_urls"] = json.loads(data.pop("base_urls_json"))
    return SourceRecord.model_validate(data)


def register_source(store: Store) -> None:
    """Explicit isolated registration; never fixes or enables an existing row."""
    source = source_definition()
    row = store.one("SELECT * FROM sources WHERE source_key=?", (SOURCE_KEY,))
    if row is not None:
        if _source_from_row(row) != source:
            raise CollectorError("existing POC source definition differs; refusing mutation")
        return
    store.execute(
        """INSERT INTO sources(source_key,vendor,plane,authority,base_urls_json,enabled,
        promotion_state,registered_state,notes,expected_identity_surface,expected_variant_surface,
        placeholder,out_of_scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (source.source_key, source.vendor, source.plane.value, source.authority.value,
         canonical_json(source.base_urls), 0, source.promotion_state, source.registered_state,
         source.notes, source.expected_identity_surface, source.expected_variant_surface, 0, 0),
    )


def _validate_sources(store: Store) -> None:
    expected = source_definition()
    row = store.one("SELECT * FROM sources WHERE source_key=?", (SOURCE_KEY,))
    if row is None or _source_from_row(row) != expected:
        raise CollectorError("POC source must be explicitly registered and match its validated definition")
    if store.one("SELECT source_key FROM sources WHERE enabled<>0 OR promotion_state='PROMOTED'"):
        raise CollectorError("isolated POC requires all sources disabled and no promotions")
    declared = next(s for s in load_sources() if s.source_key == "radxa-product")
    product = store.one("SELECT * FROM sources WHERE source_key=?", (declared.source_key,))
    if product is None or _source_from_row(product) != declared:
        raise CollectorError("PRODUCT source provenance does not match the first-party registry")


def _resolve_board(store: Store) -> tuple[str | None, dict]:
    # No inferred board key: derive candidates from durable PRODUCT-owned rows.
    rows = store.all(
        """SELECT b.*, o.payload_json, o.first_source_key, o.entity_kind AS canonical_kind,
        o.entity_key AS canonical_key, o.board_key AS canonical_board, c.content_hash AS current_hash,
        o.content_hash AS canonical_hash FROM boards b
        JOIN current_entity_observations c ON c.entity_kind='BOARD' AND c.entity_key=b.board_key
        JOIN canonical_observations o ON o.observation_id=c.observation_id
        WHERE b.vendor_key=? AND b.marketing_name=?""", ("radxa", MODEL),
    )
    eligible = []
    rejected = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        try:
            product_url = _url(payload.get("page_url", ""), product=True)
        except CollectorError:
            rejected.append(row["board_key"])
            continue
        if (row["first_seen_source"] != "radxa-product" or row["first_source_key"] != "radxa-product"
            or row["board_key"] != board_key("radxa", row["board_slug"])
            or row["canonical_kind"] != "BOARD" or row["canonical_key"] != row["board_key"]
            or row["canonical_board"] != row["board_key"] or row["current_hash"] != row["canonical_hash"]
            or content_hash(payload) != row["canonical_hash"] or payload.get("board_slug") != row["board_slug"]
            or payload.get("vendor_key") != "radxa" or payload.get("marketing_name") != MODEL
            or product_url != PRODUCT_URL.rstrip("/")
            or row["board_type"] not in {BoardType.SBC.value, BoardType.AI_SBC.value, BoardType.INDUSTRIAL_SBC.value}):
            rejected.append(row["board_key"])
            continue
        eligible.append(row["board_key"])
    reason = "linked" if len(eligible) == 1 else ("multiple PRODUCT targets" if eligible else "missing validated PRODUCT target")
    return (eligible[0] if len(eligible) == 1 else None), {
        "reason": reason, "eligible_targets": eligible, "rejected_targets": rejected,
        "signals": ["exact vendor-qualified model tab", "official model-bearing artifact paths", "validated PRODUCT name and canonical URL"],
    }


def _diagnostic(store: Store, run_id: str, observed_at: str, info: dict, unresolved: bool) -> None:
    key = "reference-diagnostic:" + SOURCE_KEY
    row = store.one("SELECT * FROM diagnostic_conditions WHERE condition_key=?", (key,))
    if unresolved:
        state = content_hash({k: v for k, v in info.items() if k != "raw_body_hash"})
        payload = canonical_json(info)
        if row is None:
            store.execute(
                """INSERT INTO diagnostic_conditions(condition_key,source_key,plane,diagnostic_type,
                entity_key,reason,state_hash,payload_json,status,first_observed_at,first_run_id,
                last_observed_at,last_run_id,open_occurrences,total_occurrences,transition_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key,SOURCE_KEY,"DOCUMENTATION","REFERENCE_LINK_UNRESOLVED",UNKNOWN,
                 "reference linkage unresolved",state,payload,"OPEN",observed_at,run_id,observed_at,run_id,1,1,1),
            )
        else:
            transition = int(row["status"] != "OPEN" or row["state_hash"] != state)
            store.execute(
                """UPDATE diagnostic_conditions SET state_hash=?,payload_json=?,status='OPEN',
                last_observed_at=?,last_run_id=?,resolved_at=NULL,resolved_run_id=NULL,
                open_occurrences=open_occurrences+1,total_occurrences=total_occurrences+1,
                transition_count=transition_count+? WHERE condition_key=?""",
                (state,payload,observed_at,run_id,transition,key),
            )
        store.execute(
            """INSERT INTO diagnostic_sightings(condition_key,run_id,source_key,observed_at,state_hash,emitted_event_key)
            VALUES (?,?,?,?,?,NULL)""", (key,run_id,SOURCE_KEY,observed_at,state),
        )
    elif row is not None and row["status"] == "OPEN":
        store.execute(
            "UPDATE diagnostic_conditions SET status='RESOLVED',resolved_at=?,resolved_run_id=? WHERE condition_key=?",
            (observed_at,run_id,key),
        )


def accept_documentation(store: Store, html: str, *, run_id: str, observed_at: str,
                         page_url: str = DOCS_URL) -> dict:
    """Atomic supporting evidence admission, with source and receipt validation."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise CollectorError("unsafe run id")
    _validate_sources(store)
    claims, info = parse_hardware(html, page_url=page_url)
    target, mapping = _resolve_board(store)
    info["mapping"] = mapping
    unresolved = not claims or target is None
    receipt = content_hash({"source_key":SOURCE_KEY,"semantic_hash":info["semantic_hash"],
                            "target":target,"unresolved":unresolved,"errors":info["errors"]})
    existing = store.one("SELECT * FROM processed_run_receipts WHERE run_id=?", (run_id,))
    if existing:
        if existing["source_key"] != SOURCE_KEY or existing["receipt_hash"] != receipt:
            raise CollectorError("run id reuse with different source or semantic evidence")
        return {"run_id":run_id,"status":"replayed","replayed":True,"events":[],"diagnostics":info}
    if store.one("SELECT run_id FROM collector_runs WHERE run_id=?", (run_id,)):
        raise CollectorError("run id already belongs to another attempt")
    baseline = store.one("SELECT source_key FROM source_baselines WHERE source_key=?", (SOURCE_KEY,)) is None
    mappings, events = [], []
    try:
        store.begin()
        _validate_sources(store)
        if _resolve_board(store)[0] != target:
            raise CollectorError("PRODUCT linkage changed during admission")
        store.execute(
            "INSERT INTO collector_runs(run_id,source_key,collector_key,started_at,finished_at,status) VALUES (?,?,?,?,?,?)",
            (run_id,SOURCE_KEY,SOURCE_KEY,observed_at,observed_at,"accepted"),
        )
        if not unresolved:
            for claim in sorted(claims, key=lambda c: c.hardware_label):
                payload = {**claim.payload(), "board_key":target}
                digest = content_hash(payload)
                key = "reference:" + SOURCE_KEY + ":" + content_hash({
                    "page":DOCS_URL,"board_key":target,"hardware_label":claim.hardware_label})
                previous = store.one("SELECT content_hash FROM current_entity_observations WHERE entity_kind=? AND entity_key=?", (KIND,key))
                row = store.one("SELECT observation_id FROM canonical_observations WHERE entity_kind=? AND entity_key=? AND content_hash=?", (KIND,key,digest))
                if row is None:
                    row_id = store.execute(
                        """INSERT INTO canonical_observations(entity_kind,entity_key,board_key,revision_key,
                        variant_key,content_hash,payload_json,first_accepted_at,first_source_key) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (KIND,key,target,UNKNOWN,UNKNOWN,digest,canonical_json(payload),observed_at,SOURCE_KEY),
                    ).lastrowid
                else:
                    row_id = row["observation_id"]
                store.execute(
                    """INSERT INTO observation_occurrences(observation_id,run_id,source_key,plane,entity_kind,
                    entity_key,observed_at,content_hash) VALUES (?,?,?,?,?,?,?,?)""",
                    (row_id,run_id,SOURCE_KEY,"DOCUMENTATION",KIND,key,observed_at,digest),
                )
                if previous is None or previous["content_hash"] != digest:
                    store.execute(
                        """INSERT INTO current_entity_observations(entity_kind,entity_key,observation_id,content_hash,updated_at,updated_run_id)
                        VALUES (?,?,?,?,?,?) ON CONFLICT(entity_kind,entity_key) DO UPDATE SET
                        observation_id=excluded.observation_id,content_hash=excluded.content_hash,
                        updated_at=excluded.updated_at,updated_run_id=excluded.updated_run_id""",
                        (KIND,key,row_id,digest,observed_at,run_id),
                    )
                    before = previous["content_hash"] if previous else UNKNOWN
                    event = EventRecord(
                        event_key=content_hash({"run_id":run_id,"entity_key":key,"from":before,"to":digest}),
                        event_type=EventType.NEW_REFERENCE,entity_kind=EntityKind.DOCUMENTATION_REFERENCE,
                        entity_key=key,board_key=target,revision_key=UNKNOWN,variant_key=UNKNOWN,
                        source_key=SOURCE_KEY,from_hash=before,to_hash=digest,baseline_silent=True,
                        payload={"reference_scope":KIND,"market_novelty":False,"effective_at":UNKNOWN,
                                 "transition":"historical_reference_discovered" if previous is None else "reference_evidence_updated"},
                        code_revision=SOURCE_REVISION,
                    )
                    store.execute(
                        """INSERT INTO events(event_key,event_type,entity_kind,entity_key,board_key,revision_key,variant_key,
                        source_key,run_id,from_hash,to_hash,baseline_silent,payload_json,created_at,code_revision)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (event.event_key,event.event_type.value,KIND,key,target,UNKNOWN,UNKNOWN,SOURCE_KEY,
                         run_id,before,digest,1,canonical_json(event.payload),observed_at,event.code_revision),
                    )
                    # Intentionally no notification row: references have no delivery authority.
                    events.append(event.event_key)
                mappings.append({"reference_key":key,"board_key":target,"hardware_label":claim.hardware_label,
                                 "content_hash":digest,"observation_id":row_id})
            if baseline:
                store.execute("INSERT INTO source_baselines VALUES (?,?,?,?)", (SOURCE_KEY,run_id,observed_at,len(claims)))
        _diagnostic(store,run_id,observed_at,info,unresolved)
        store.execute("INSERT INTO processed_run_receipts VALUES (?,?,?,?,?,?)",
                      (run_id,SOURCE_KEY,receipt,observed_at,len(mappings),len(events)))
        store.commit()
    except Exception:
        store.rollback()
        raise
    return {"run_id":run_id,"status":"accepted","replayed":False,"baseline":baseline,
            "mappings":mappings,"unresolved":unresolved,"events":events,"diagnostics":info,
            "notifications":0,"market_novelty":False,"field_changed":0}


class _BoundedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _url(newurl, product=req.full_url.startswith("https://radxa.com/"))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str, *, product: bool = False) -> tuple[str, dict]:
    _url(url, product=product)
    opener = build_opener(_BoundedRedirect())
    with opener.open(Request(url,headers={"User-Agent":"board-clank/0.1 (manual-isolated-reference-poc)"}),timeout=30) as r:
        _url(r.url, product=product)
        if "text/html" not in (r.headers.get("Content-Type") or ""):
            raise CollectorError("first-party response is not HTML")
        raw = r.read(2_000_001)
        if len(raw) > 2_000_000:
            raise CollectorError("bounded page exceeds 2MB")
        text = raw.decode(r.headers.get_content_charset() or "utf-8",errors="strict")
        meta = {"requested_url":url,"final_url":r.url,"status":r.status,"headers":dict(r.headers),
                "raw_sha256":hashlib.sha256(raw).hexdigest(),"size":len(raw)}
    return text,meta


def record_fetch_failure(store: Store, *, run_id: str, observed_at: str, error: str) -> None:
    _validate_sources(store)
    if store.one("SELECT run_id FROM collector_runs WHERE run_id=?", (run_id,)):
        raise CollectorError("failed attempt run id already exists")
    try:
        store.begin()
        store.execute(
            "INSERT INTO collector_runs(run_id,source_key,collector_key,started_at,finished_at,status,error) VALUES (?,?,?,?,?,?,?)",
            (run_id,SOURCE_KEY,SOURCE_KEY,observed_at,observed_at,"failed",error),
        )
        store.execute("INSERT INTO run_errors(run_id,source_key,message,created_at) VALUES (?,?,?,?)",
                      (run_id,SOURCE_KEY,error,observed_at))
        store.commit()
    except Exception:
        store.rollback()
        raise


def main(argv: list[str] | None = None) -> int:
    """A new isolated directory is required; no default/canonical DB path exists."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experimental-live", action="store_true")
    args = parser.parse_args(argv)
    if args.qualification_root.is_symlink():
        parser.error("qualification root cannot be a symbolic link")
    root = args.qualification_root.resolve()
    marker = root / "isolated-reference-poc.json"
    marker_data = {"source_key":SOURCE_KEY,"purpose":"isolated qualification only","database":"qualification.db"}
    now = datetime.now(timezone.utc).isoformat()
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
            raise CollectorError("unsafe run id")
        if root.exists() and not marker.exists():
            raise CollectorError("existing directory is not a marked isolated qualification workspace")
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != marker_data:
            raise CollectorError("qualification marker does not match this POC")
        root.mkdir(parents=True,exist_ok=True)
        db = root / "qualification.db"
        if db.is_symlink() or marker.is_symlink():
            raise CollectorError("qualification files cannot be symbolic links")
        capture = root / args.run_id
        if capture.exists():
            raise CollectorError("capture directory already exists; retain evidence and choose a distinct run id")
        capture.mkdir()
        if not marker.exists():
            marker.write_text(canonical_json(marker_data)+"\n",encoding="utf-8")
            from board_clank.collectors.radxa import parse_product_html
            from board_clank.models import CollectorRunRequest
            from board_clank.pipeline import Pipeline
            with Store(db) as seed:
                sync_sources_to_store(seed)
                if args.experimental_live:
                    product_html,product_meta = fetch_page(PRODUCT_URL,product=True)
                    (capture/"product.html").write_text(product_html,encoding="utf-8")
                    (capture/"product-fetch.json").write_text(canonical_json(product_meta)+"\n",encoding="utf-8")
                else:
                    product_html = _FIXTURE.with_name("rock5b-product-seed.html").read_text(encoding="utf-8")
                drafts,diagnostics = parse_product_html(product_html,page_url=PRODUCT_URL,observed_at=now,historical_known=True)
                if not drafts or any(d.evidence_insufficient or d.identity_conflict for d in drafts):
                    raise CollectorError("isolated PRODUCT seed did not resolve")
                request = CollectorRunRequest(run_id="product-seed",source_key="radxa-product",
                    collector_key="radxa-product",started_at=now,observations=drafts,diagnostics=diagnostics)
                Pipeline(seed).accept_run(request)
                register_source(seed)
        with Store(db,migrate=False) as store:
            _validate_sources(store)
            if args.experimental_live:
                try:
                    html,meta = fetch_page(DOCS_URL)
                except (CollectorError, OSError, ValueError) as e:
                    record_fetch_failure(store,run_id=args.run_id,observed_at=now,error=str(e))
                    raise
            else:
                html = _FIXTURE.read_text(encoding="utf-8")
                meta = {"mode":"offline-fixture","file":str(_FIXTURE)}
            (capture/"documentation.html").write_text(html,encoding="utf-8")
            (capture/"fetch.json").write_text(canonical_json(meta)+"\n",encoding="utf-8")
            result = accept_documentation(store,html,run_id=args.run_id,observed_at=now)
        from board_clank.observer import full_snapshot
        result["observer"] = full_snapshot(db)
        (capture/"result.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        print(json.dumps(result,indent=2,sort_keys=True))
        return 2 if result.get("unresolved") else 0
    except (CollectorError, OSError, ValueError) as e:
        error = {"status":"failed","error":str(e),"source_key":SOURCE_KEY,"market_novelty":False}
        if 'capture' in locals() and capture.exists():
            (capture/"failure.json").write_text(canonical_json(error)+"\n",encoding="utf-8")
        print(json.dumps(error,indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
