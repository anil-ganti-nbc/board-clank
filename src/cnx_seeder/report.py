"""Canonical report.json and fetch-log.jsonl derived from the queue."""

from __future__ import annotations

import json
import sqlite3

from cnx_seeder.store import Queue


def _loads(raw: str | None) -> list:
    if not raw:
        return []
    value = json.loads(raw)
    return value if isinstance(value, list) else []


def build_report(con: sqlite3.Connection) -> dict:
    runs = []
    for row in con.execute("SELECT * FROM runs ORDER BY started_at, run_id"):
        run_id = row["run_id"]
        new_qualified = con.execute(
            "SELECT COUNT(*) AS n FROM qualified_candidates WHERE first_run_id = ?",
            (run_id,),
        ).fetchone()["n"]
        runs.append(
            {
                "alias_table_version": row["alias_table_version"],
                "article_urls": _loads(row["article_urls_json"]),
                "code_revision": row["code_revision"],
                "finished_at": row["finished_at"],
                "listing_url": row["listing_url"],
                "max_articles": row["max_articles"],
                "max_listing_pages": row["max_listing_pages"],
                "new_qualified": new_qualified,
                "roster_sha256": row["roster_sha256"],
                "run_id": run_id,
                "sample_source": row["sample_source"],
                "sample_window_end": row["sample_window_end"],
                "sample_window_start": row["sample_window_start"],
                "started_at": row["started_at"],
                "status": row["status"],
            }
        )
    fetches = []
    for row in con.execute(
        "SELECT * FROM fetches ORDER BY run_id, fetched_at, url, attempt, fetch_id"
    ):
        fetches.append(
            {
                "attempt": row["attempt"],
                "byte_length": row["byte_length"],
                "content_sha256": row["content_sha256"],
                "elapsed_ms": row["elapsed_ms"],
                "error": row["error"],
                "fetched_at": row["fetched_at"],
                "http_status": row["http_status"],
                "outcome": row["outcome"],
                "robots_decision": row["robots_decision"],
                "run_id": row["run_id"],
                "url": row["url"],
            }
        )
    leads = []
    for row in con.execute("SELECT * FROM leads"):
        leads.append(
            {
                "article_title": row["article_title"],
                "board_surface_url": row["board_surface_url"],
                "classification": row["classification"],
                "cnx_article_url": row["cnx_article_url"],
                "comparison_mentions": _loads(row["comparison_mentions_json"]),
                "discovered_name": row["discovered_name"],
                "homepage_url": row["homepage_url"],
                "lead_key": row["lead_key"],
                "normalized_name": row["normalized_name"],
                "primary_domain": row["primary_domain"],
                "primary_url": row["primary_url"],
                "qualified": row["qualified"],
                "reason_code": row["reason_code"],
            }
        )
    leads.sort(
        key=lambda item: (
            item["normalized_name"] or "",
            item["primary_domain"] or "",
            item["cnx_article_url"] or "",
        )
    )
    qualified = []
    for row in con.execute("SELECT * FROM qualified_candidates"):
        sightings = [
            {
                "cnx_article_url": item["cnx_article_url"],
                "run_id": item["run_id"],
                "seen_at": item["seen_at"],
            }
            for item in con.execute(
                """
                SELECT run_id, cnx_article_url, seen_at FROM article_sightings
                WHERE candidate_key = ?
                ORDER BY run_id, cnx_article_url
                """,
                (row["candidate_key"],),
            )
        ]
        qualified.append(
            {
                "article_title": row["article_title"],
                "board_surface_url": row["board_surface_url"],
                "candidate_key": row["candidate_key"],
                "cnx_article_url": row["cnx_article_url"],
                "content_sha256": row["content_sha256"],
                "first_run_id": row["first_run_id"],
                "homepage_host": row["homepage_host"],
                "homepage_url": row["homepage_url"],
                "inserted_at": row["inserted_at"],
                "normalized_name": row["normalized_name"],
                "primary_domain": row["primary_domain"],
                "primary_host": row["primary_host"],
                "primary_url": row["primary_url"],
                "sightings": sightings,
            }
        )
    qualified.sort(
        key=lambda item: (
            item["normalized_name"] or "",
            item["primary_domain"] or "",
            item["cnx_article_url"] or "",
        )
    )
    return {"fetches": fetches, "leads": leads, "qualified": qualified, "runs": runs}


def render_report(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    text = text.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def write_report(queue: Queue) -> bytes:
    payload = build_report(queue.con)
    rendered = render_report(payload).encode("utf-8")
    (queue.state_dir / "report.json").write_bytes(rendered)
    lines = []
    for fetch in payload["fetches"]:
        lines.append(json.dumps(fetch, ensure_ascii=False, sort_keys=True))
    body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    (queue.state_dir / "fetch-log.jsonl").write_bytes(body)
    return rendered
