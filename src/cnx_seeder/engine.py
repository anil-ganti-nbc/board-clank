"""Fixture and live runs, plus replay of a frozen sample."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from cnx_seeder.aliases import AliasRow, load_alias_table, match_alias
from cnx_seeder.bounds import (
    ACCESS_CONTROL_STATUSES,
    ALIAS_TABLE_VERSION,
    FEED_URL,
    LISTING_URL,
    MAX_ARTICLES,
    MAX_LISTING_PAGES,
    MAX_OEM_FETCHES_PER_LEAD,
)
from cnx_seeder.classify import ALIAS_CLASS, DENYLIST, SOC_DOMAINS, SOC_NAMES, is_product_only
from cnx_seeder.extract import (
    ParsedPage,
    extract_subject,
    feed_is_malformed,
    has_cart,
    has_identity,
    has_scope,
    is_about_path,
    is_surface_path,
    listing_links,
    page_has_tokens,
    parse_feed_items,
    parse_html,
    foreign_brands,
)
from cnx_seeder.http import (
    FetchRecord,
    Fetcher,
    FixtureTransport,
    HttpResponse,
    LiveClock,
    LiveTransport,
    Transport,
    VirtualClock,
    parse_stamp,
    stamp,
)
from cnx_seeder.normalize import candidate_key, host_of, is_cnx_host, lead_key, normalize_tokens, registrable_domain
from cnx_seeder.report import write_report
from cnx_seeder.roster import RosterError, assert_alias_coverage, load_roster
from cnx_seeder.store import Queue


@dataclass
class Decision:
    classification: str
    reason: str
    qualified: bool = False
    primary_url: str | None = None
    primary_domain: str | None = None
    primary_host: str | None = None
    homepage_url: str | None = None
    homepage_host: str | None = None
    content_sha256: str | None = None
    mentions: list[str] = field(default_factory=list)
    normalized_name: str = ""
    discovered_name: str = ""


@dataclass
class Article:
    url: str
    title: str
    published: str | None = None


def _window(values: list[str | None]) -> tuple[str | None, str | None]:
    parsed: list[datetime] = []
    for raw in values:
        if not raw:
            continue
        try:
            parsed.append(parsedate_to_datetime(raw))
            continue
        except (TypeError, ValueError, IndexError):
            pass
        try:
            parsed.append(parse_stamp(raw))
        except ValueError:
            continue
    if not parsed:
        return None, None
    parsed.sort()
    return stamp(parsed[0]), stamp(parsed[-1])


def _persist(queue: Queue, run_id: str, record: FetchRecord) -> str | None:
    digest = record.content_sha256
    if record.body and record.outcome != "blocked":
        digest = queue.write_body(record.body)
    elif record.body and record.error == "body_cap":
        digest = queue.write_body(record.body)
    queue.add_fetch(
        {
            "run_id": run_id,
            "url": record.url,
            "attempt": record.attempt,
            "fetched_at": record.fetched_at,
            "http_status": record.http_status,
            "content_sha256": digest,
            "byte_length": record.byte_length,
            "elapsed_ms": record.elapsed_ms,
            "robots_decision": record.robots_decision,
            "outcome": record.outcome,
            "error": record.error,
        }
    )
    return digest


def _persist_new(queue: Queue, run_id: str, fetcher: Fetcher, seen: int) -> int:
    for record in fetcher.history[seen:]:
        _persist(queue, run_id, record)
    return len(fetcher.history)


def _last_ok(records: list[FetchRecord]) -> FetchRecord | None:
    if not records:
        return None
    last = records[-1]
    if last.outcome == "ok" and last.http_status == 200 and last.error != "body_cap":
        return last
    return None


def _blocked_reason(records: list[FetchRecord]) -> str:
    if not records:
        return "fetch_failed"
    last = records[-1]
    if last.error == "robots_disallow" or last.robots_decision == "disallow":
        return "robots_disallow"
    if last.http_status in ACCESS_CONTROL_STATUSES or last.error == "http_blocked":
        return "http_blocked"
    return "fetch_failed"


def _same_domain(url: str, domain: str) -> bool:
    host = host_of(url)
    if host is None or is_cnx_host(host):
        return False
    if not url.startswith("https://"):
        return False
    return registrable_domain(host) == domain


def _verify(
    subject: tuple[str, ...],
    domain: str,
    links: list,
    fetcher: Fetcher,
    queue: Queue,
    run_id: str,
    cache: dict[str, list[FetchRecord]],
) -> Decision:
    name = " ".join(subject)
    home = f"https://{domain}/"
    about = next((link.href for link in links if _same_domain(link.href, domain) and is_about_path(link.href)), None)
    surface = next(
        (link.href for link in links if _same_domain(link.href, domain) and is_surface_path(link.href)),
        None,
    )
    planned: list[str] = []
    for url in (home, about, surface):
        if url and url not in planned:
            planned.append(url)
    for link in links:
        if _same_domain(link.href, domain) and link.href not in planned:
            planned.append(link.href)
    planned = planned[:MAX_OEM_FETCHES_PER_LEAD]
    pages: list[tuple[FetchRecord, ParsedPage]] = []
    surface_attempt: FetchRecord | None = None
    for url in planned:
        if url in cache:
            records = cache[url]
        else:
            before = len(fetcher.history)
            records = fetcher.fetch(url)
            _persist_new(queue, run_id, fetcher, before)
            cache[url] = records
        if url == surface:
            surface_attempt = records[-1] if records else None
        ok = _last_ok(records)
        if ok is None or ok.error == "body_cap":
            continue
        if not (ok.final_url or ok.url).startswith("https://"):
            continue
        page = parse_html(ok.body, base_url=ok.final_url or url, content_type=ok.content_type or "text/html")
        if page.malformed or page.instruction:
            continue
        final = ok.final_url or url
        host = host_of(final)
        if host is None or registrable_domain(host) != domain:
            continue
        pages.append((ok, page))

    own_pages: list[tuple[FetchRecord, ParsedPage]] = []
    for record, page in pages:
        final = record.final_url or record.url
        final_host = host_of(final)
        if final_host is not None and registrable_domain(final_host) == domain:
            own_pages.append((record, page))
    pages = own_pages
    texts = "\n".join(page.text for _, page in pages)
    brands: set[str] = set()
    for _, page in pages:
        brands |= foreign_brands(page.text, subject)
    # Two other brands mark a reseller only when this vendor's own site shows
    # no company identity. A maker homepage that says "we design" is not a
    # reseller because its shop page also names a chip vendor, and a shared
    # widget page is not consulted at all.
    if len(brands) >= 2 and not has_identity(texts):
        return Decision("reseller", "reseller", normalized_name=name, discovered_name=name, primary_domain=domain)
    if has_cart(texts) and not has_identity(texts):
        return Decision(
            "reseller", "storefront_only", normalized_name=name, discovered_name=name, primary_domain=domain
        )

    homepage_url = None
    homepage_host = None
    for record, page in pages:
        final = record.final_url or record.url
        if page_has_tokens(page, subject) and has_identity(page.text):
            homepage_url = final
            homepage_host = host_of(final)
            break

    primary_url = None
    primary_host = None
    content_hash = None
    brand_missing_on_surface = False
    for record, page in pages:
        final = record.final_url or record.url
        if not is_surface_path(final):
            continue
        if page_has_tokens(page, subject) and has_scope(page.text):
            primary_url = final
            primary_host = host_of(final)
            content_hash = record.content_sha256
            break
        if has_scope(page.text) and not page_has_tokens(page, subject):
            brand_missing_on_surface = True

    if homepage_url and primary_url and primary_host and homepage_host:
        return Decision(
            "board_maker",
            "qualified",
            True,
            primary_url,
            domain,
            primary_host,
            homepage_url,
            homepage_host,
            content_hash,
            normalized_name=name,
            discovered_name=name,
        )
    if homepage_url and brand_missing_on_surface:
        return Decision(
            "unresolved",
            "brand_domain_mismatch",
            homepage_url=homepage_url,
            homepage_host=homepage_host,
            primary_domain=domain,
            normalized_name=name,
            discovered_name=name,
        )
    if homepage_url and surface and surface_attempt is not None and surface_attempt.outcome != "ok":
        return Decision(
            "unresolved",
            "board_surface_unresolved",
            homepage_url=homepage_url,
            homepage_host=homepage_host,
            primary_domain=domain,
            normalized_name=name,
            discovered_name=name,
        )
    return Decision(
        "unresolved",
        "board_maker_unresolved",
        homepage_url=homepage_url,
        homepage_host=homepage_host,
        primary_domain=domain,
        normalized_name=name,
        discovered_name=name,
    )


def _decide(
    title: str,
    page: ParsedPage | None,
    rows: list[AliasRow],
    fetcher: Fetcher,
    queue: Queue,
    run_id: str,
    cache: dict[str, list[FetchRecord]],
    *,
    fetch_reason: str | None = None,
) -> Decision:
    if fetch_reason:
        return Decision("unresolved", fetch_reason)
    if page is not None and page.instruction:
        return Decision("unresolved", "instruction_bearing_rejected")
    if page is not None and page.malformed:
        return Decision("unresolved", "malformed_page")
    alias_names = tuple(name for row in rows for name in row.names)
    extraction = extract_subject(title, page, alias_names=alias_names)
    subject = extraction.subject
    domain = extraction.domain
    mentions = list(extraction.mentions)
    if extraction.reason == "vendor_name_unresolved" and is_product_only(normalize_tokens(title)):
        return Decision(
            "single_product_name",
            "single_product_name",
            mentions=mentions,
            discovered_name="",
            normalized_name="",
        )
    alias = match_alias(rows, subject, domain) if (subject or domain) else None
    if alias is not None:
        classification, reason = ALIAS_CLASS[alias.role]
        return Decision(
            classification,
            reason,
            primary_url=extraction.chosen_url,
            primary_domain=domain,
            mentions=mentions,
            normalized_name=" ".join(subject),
            discovered_name=" ".join(subject),
        )
    if subject in SOC_NAMES or (domain in SOC_DOMAINS):
        return Decision(
            "soc_vendor",
            "soc_vendor",
            primary_domain=domain,
            mentions=mentions,
            normalized_name=" ".join(subject),
            discovered_name=" ".join(subject),
        )
    if domain in DENYLIST:
        classification, reason = DENYLIST[domain]
        return Decision(
            classification,
            reason,
            primary_domain=domain,
            mentions=mentions,
            normalized_name=" ".join(subject),
            discovered_name=" ".join(subject),
        )
    if extraction.reason:
        return Decision(
            "unresolved",
            extraction.reason,
            mentions=mentions,
            normalized_name=" ".join(subject),
            discovered_name=" ".join(subject),
        )
    if not subject or is_product_only(subject):
        return Decision("single_product_name", "single_product_name", mentions=mentions)
    if domain is None:
        return Decision(
            "unresolved",
            "primary_domain_unresolved",
            mentions=mentions,
            normalized_name=" ".join(subject),
            discovered_name=" ".join(subject),
        )
    decision = _verify(subject, domain, extraction.links, fetcher, queue, run_id, cache)
    decision.mentions = mentions
    return decision


def _store_lead(
    queue: Queue,
    run_id: str,
    seen_at: str,
    article: Article,
    decision: Decision,
) -> None:
    normalized = decision.normalized_name
    row = {
        "lead_key": lead_key(article.url, normalized),
        "cnx_article_url": article.url,
        "article_title": article.title,
        "discovered_name": decision.discovered_name,
        "normalized_name": normalized,
        "mentions": decision.mentions,
        "classification": decision.classification,
        "reason_code": decision.reason,
        "primary_url": decision.primary_url,
        "primary_domain": decision.primary_domain,
        "primary_host": decision.primary_host,
        "homepage_url": decision.homepage_url,
        "homepage_host": decision.homepage_host,
        "board_surface_url": decision.primary_url,
        "qualified": decision.qualified,
    }
    queue.add_lead(row, seen_at, run_id)
    if not decision.qualified or not decision.primary_domain or not decision.primary_url:
        return
    if not decision.homepage_url or not decision.primary_host or not decision.homepage_host:
        return
    queue.add_candidate(
        {
            "candidate_key": candidate_key(normalized, decision.primary_domain),
            "cnx_article_url": article.url,
            "article_title": article.title,
            "primary_url": decision.primary_url,
            "primary_domain": decision.primary_domain,
            "primary_host": decision.primary_host,
            "homepage_url": decision.homepage_url,
            "homepage_host": decision.homepage_host,
            "normalized_name": normalized,
            "content_sha256": decision.content_sha256 or "",
        },
        seen_at,
        run_id,
    )


def _take_feed(body: bytes) -> list[Article]:
    if feed_is_malformed(body):
        return []
    items = parse_feed_items(body)
    return [Article(url, title, published) for url, title, published in items[:MAX_ARTICLES]]


def _html_sample(fetcher: Fetcher) -> tuple[list[Article], str]:
    articles: list[Article] = []
    seen: set[str] = set()
    url = LISTING_URL
    pages = 0
    while pages < MAX_LISTING_PAGES and len(articles) < MAX_ARTICLES:
        records = fetcher.fetch(url)
        pages += 1
        seen.add(url)
        ok = _last_ok(records)
        if ok is None:
            break
        page = parse_html(ok.body, base_url=ok.final_url or url, content_type=ok.content_type or "text/html")
        if page.malformed or page.instruction:
            break
        found, next_pages = listing_links(page)
        for link in found:
            if link in {item.url for item in articles}:
                continue
            anchor = next((item.anchor for item in page.links if item.href == link), "")
            articles.append(Article(link, anchor or link))
            if len(articles) >= MAX_ARTICLES:
                break
        nxt = next((item for item in next_pages if item not in seen), None)
        if nxt is None or pages >= MAX_LISTING_PAGES:
            break
        url = nxt
    return articles[:MAX_ARTICLES], "html"


def acquire(fetcher: Fetcher) -> tuple[str, str, list[Article], str]:
    """Return sample_source, listing_url, articles, run status."""
    records = fetcher.fetch(FEED_URL)
    if not records:
        return "feed", FEED_URL, [], "completed"
    last = records[-1]
    if last.robots_decision == "disallow":
        return "feed", FEED_URL, [], "completed"
    if last.http_status in ACCESS_CONTROL_STATUSES or (
        last.error == "http_blocked" and last.http_status in ACCESS_CONTROL_STATUSES
    ):
        return "feed", FEED_URL, [], "blocked"
    if any(record.robots_decision == "robots_unavailable" for record in records):
        return "feed", FEED_URL, [], "completed"
    use_html = False
    if last.outcome != "ok" or last.http_status != 200 or last.error == "body_cap":
        use_html = last.http_status == 404
        if not use_html:
            return "feed", FEED_URL, [], "completed"
    else:
        if feed_is_malformed(last.body) or not _take_feed(last.body):
            use_html = True
        else:
            return "feed", FEED_URL, _take_feed(last.body), "completed"
    if use_html:
        articles, source = _html_sample(fetcher)
        return source, LISTING_URL, articles, "completed"
    return "feed", FEED_URL, [], "completed"


def _process_articles(
    queue: Queue,
    run_id: str,
    fetcher: Fetcher,
    rows: list[AliasRow],
    articles: list[Article],
    seen_at: str,
) -> None:
    cache: dict[str, list[FetchRecord]] = {}
    for article in articles:
        if article.url in cache:
            records = cache[article.url]
        else:
            before = len(fetcher.history)
            records = fetcher.fetch(article.url)
            _persist_new(queue, run_id, fetcher, before)
            cache[article.url] = records
        if not records:
            _store_lead(
                queue,
                run_id,
                seen_at,
                article,
                Decision("unresolved", "fetch_failed"),
            )
            continue
        last = records[-1]
        if last.robots_decision == "disallow" or last.error == "robots_disallow":
            _store_lead(queue, run_id, seen_at, article, Decision("unresolved", "robots_disallow"))
            continue
        if last.error == "body_cap" or (last.outcome != "ok"):
            _store_lead(queue, run_id, seen_at, article, Decision("unresolved", _blocked_reason(records)))
            continue
        page = parse_html(last.body, base_url=last.final_url or article.url, content_type=last.content_type)
        decision = _decide(article.title, page, rows, fetcher, queue, run_id, cache)
        _store_lead(queue, run_id, seen_at, article, decision)


def run_sample(
    queue: Queue,
    *,
    run_id: str,
    code_revision: str,
    roster_path: Path,
    fetcher: Fetcher,
    started: datetime,
) -> int:
    roster = load_roster(roster_path)
    rows = load_alias_table()
    assert_alias_coverage(roster, rows)
    sample_source, listing_url, articles, status = acquire(fetcher)
    start_s, end_s = _window([item.published for item in articles])
    now_stamp = stamp(started)
    queue.con.execute(
        """
        INSERT INTO runs(
            run_id, started_at, finished_at, code_revision, alias_table_version, roster_sha256,
            sample_source, listing_url, sample_window_start, sample_window_end, article_urls_json,
            max_listing_pages, max_articles, status
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            stamp(started),
            code_revision,
            ALIAS_TABLE_VERSION,
            roster.sha256,
            sample_source,
            listing_url,
            start_s,
            end_s,
            json.dumps([item.url for item in articles]),
            MAX_LISTING_PAGES,
            MAX_ARTICLES,
            "running",
        ),
    )
    _persist_new(queue, run_id, fetcher, 0)
    if status != "blocked":
        _process_articles(queue, run_id, fetcher, rows, articles, now_stamp)
    finished = stamp(fetcher.clock.now)
    queue.con.execute(
        "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
        (finished, status if status == "blocked" else "completed", run_id),
    )
    queue.commit()
    write_report(queue)
    _print_summary(queue, run_id)
    return 0


def _print_summary(queue: Queue, run_id: str, *, replay: bool = False, live: bool = False) -> None:
    row = queue.con.execute("SELECT status, article_urls_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    leads = queue.con.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    qualified = queue.con.execute("SELECT COUNT(*) AS n FROM qualified_candidates").fetchone()["n"]
    new_qualified = queue.con.execute(
        "SELECT COUNT(*) AS n FROM qualified_candidates WHERE first_run_id = ?",
        (run_id,),
    ).fetchone()["n"]
    payload: dict[str, object] = {
        "leads": leads,
        "new_qualified": new_qualified,
        "qualified": qualified,
        "run_id": run_id,
        "status": None if row is None else row["status"],
    }
    if replay:
        articles = json.loads(row["article_urls_json"]) if row is not None else []
        payload["article_count"] = len(articles)
        payload["article_set"] = "reused"
        payload["cnx_fetches"] = "reused"
        payload["oem_fetches"] = "reused"
        note = "article set reused; OEM fetches reused from the source run; no OEM network refetch"
        if live:
            note += "; --live does not open OEM sockets"
        payload["replay_note"] = note
    print(json.dumps(payload, sort_keys=True))


def print_report_summary(queue: Queue) -> None:
    rows = queue.con.execute("SELECT run_id FROM runs ORDER BY started_at, run_id").fetchall()
    if not rows:
        print(json.dumps({"leads": 0, "qualified": 0, "runs": 0}, sort_keys=True))
        return
    for row in rows:
        _print_summary(queue, str(row["run_id"]))


def _copy_frozen_fetches(queue: Queue, source_id: str, run_id: str) -> None:
    rows = queue.con.execute(
        "SELECT * FROM fetches WHERE run_id = ? ORDER BY fetch_id",
        (source_id,),
    ).fetchall()
    for row in rows:
        host = host_of(row["url"])
        if host is None or not is_cnx_host(host):
            continue
        queue.add_fetch(
            {
                "run_id": run_id,
                "url": row["url"],
                "attempt": row["attempt"],
                "fetched_at": row["fetched_at"],
                "http_status": row["http_status"],
                "content_sha256": row["content_sha256"],
                "byte_length": row["byte_length"],
                "elapsed_ms": row["elapsed_ms"],
                "robots_decision": row["robots_decision"],
                "outcome": "reused",
                "error": row["error"],
            }
        )


def _copy_sightings(queue: Queue, source_id: str, run_id: str, seen_at: str) -> None:
    for row in queue.con.execute(
        "SELECT lead_key FROM lead_sightings WHERE run_id = ?",
        (source_id,),
    ):
        queue.con.execute(
            "INSERT OR IGNORE INTO lead_sightings(run_id, lead_key, seen_at) VALUES (?, ?, ?)",
            (run_id, row["lead_key"], seen_at),
        )
    for row in queue.con.execute(
        "SELECT candidate_key, cnx_article_url FROM article_sightings WHERE run_id = ?",
        (source_id,),
    ):
        queue.con.execute(
            """
            INSERT OR IGNORE INTO article_sightings(run_id, candidate_key, cnx_article_url, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, row["candidate_key"], row["cnx_article_url"], seen_at),
        )


def replay_sample(
    queue: Queue,
    *,
    run_id: str,
    code_revision: str,
    source_id: str,
    live: bool,
    started: datetime,
    transport: Transport | None,
    clock: VirtualClock | LiveClock,
) -> int:
    source = queue.con.execute("SELECT * FROM runs WHERE run_id = ?", (source_id,)).fetchone()
    if source is None:
        raise RosterError("replay source run is missing")
    queue.con.execute(
        """
        INSERT INTO runs(
            run_id, started_at, finished_at, code_revision, alias_table_version, roster_sha256,
            sample_source, listing_url, sample_window_start, sample_window_end, article_urls_json,
            max_listing_pages, max_articles, status
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')
        """,
        (
            run_id,
            stamp(started),
            code_revision,
            source["alias_table_version"],
            source["roster_sha256"],
            source["sample_source"],
            source["listing_url"],
            source["sample_window_start"],
            source["sample_window_end"],
            source["article_urls_json"],
            source["max_listing_pages"],
            source["max_articles"],
        ),
    )
    _copy_frozen_fetches(queue, source_id, run_id)
    _copy_sightings(queue, source_id, run_id, stamp(clock.now))
    # Stored OEM bodies stay on the source run. Replay does not GET them again,
    # including when --live is set.
    _ = transport
    queue.con.execute(
        "UPDATE runs SET finished_at = ?, status = 'completed' WHERE run_id = ?",
        (stamp(clock.now), run_id),
    )
    queue.commit()
    write_report(queue)
    _print_summary(queue, run_id, replay=True, live=live)
    return 0


def make_clock(now: str | None, live: bool) -> VirtualClock | LiveClock:
    if live and now is None:
        return LiveClock()
    if now is None:
        raise RosterError("fixture run requires --now")
    return VirtualClock(parse_stamp(now))


def make_transport(fixture: Path | None, live: bool) -> Transport:
    if live:
        return LiveTransport()
    if fixture is None:
        raise RosterError("fixture run requires --fixture")
    return FixtureTransport(fixture)


def noop_existing(queue: Queue, run_id: str) -> int:
    write_report(queue)
    _print_summary(queue, run_id)
    return 0
