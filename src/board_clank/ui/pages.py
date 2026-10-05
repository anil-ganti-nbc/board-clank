"""Server-rendered operator pages. Business decisions stay in the research bridge."""

from __future__ import annotations

from html import escape
from typing import Any

from board_clank.ui.service import UiIdentity, activity_stages

_SHAPES = {
    "IMPORTED": "○",
    "QUALIFYING": "◐",
    "QUALIFIED": "▣",
    "REJECTED": "✖",
    "QUARANTINED": "▢",
}


def status_text(status: str | None) -> str:
    label = status or "UNKNOWN"
    return f"{_SHAPES.get(label, '?')} {label}"


def _e(value: object) -> str:
    return escape("" if value is None else str(value))


def _stamp(role: str, value: object) -> str:
    shown = value if value else "UNKNOWN"
    return (
        f'<p data-timestamp-role="{_e(role)}" data-timezone="UTC">'
        f'{_e(role)} (UTC): {_e(shown)}</p>'
    )


def _layout(title: str, identity: UiIdentity, body: str, *, notice: dict[str, Any] | None = None) -> str:
    banner = ""
    if notice and notice.get("message"):
        kind = "success" if notice.get("success") else ("committed" if notice.get("committed") else "refused")
        banner = (
            f'<p data-outcome="{kind}" data-action="{_e(notice.get("action"))}">'
            f'{_e(notice.get("message"))}'
            f'{"" if not notice.get("reason") else " — " + _e(notice.get("reason"))}'
            f"</p>"
        )
    endpoint = f'{identity.bind_host}:{identity.bind_port}'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(title)} — Board Clank prototype</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.5rem; line-height: 1.4; }}
nav a {{ margin-right: 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #222; padding: 0.3rem 0.5rem; text-align: left; vertical-align: top; }}
.banner {{ padding: 0.6rem; border: 2px solid #222; }}
</style>
</head>
<body data-collection="idle">
<p class="banner">Prototype / non-production. Research leads are non-authoritative until independently qualified.</p>
<p data-health="UNKNOWN">Runtime health: UNKNOWN. Lead counts are not evidence that this prototype is healthy.</p>
<p data-source-health="UNKNOWN">Source operational health: UNKNOWN. This is separate from research lead counts. A quiet list is not a broken source.</p>
<p data-bind="{_e(endpoint)}">Loopback bind: {_e(endpoint)}</p>
<nav>
<a href="/">Overview</a>
<a href="/leads">Research leads</a>
<a href="/archive">Recently reviewed</a>
<a href="/activity">Activity</a>
<a href="/about">About / safety</a>
</nav>
{banner}
<h1>{_e(title)}</h1>
{body}
</body>
</html>
"""


def _status(status: str | None) -> str:
    label = status or "UNKNOWN"
    return f'<span data-status="{_e(label)}">{_e(status_text(label))}</span>'


def overview_page(payload: dict[str, Any]) -> str:
    identity: UiIdentity = payload["identity"]
    counts = payload["counts"] or {"none": 0}
    count_rows = "".join(
        f"<tr><td>{_e(name)}</td><td>{_e(count)}</td></tr>" for name, count in sorted(counts.items())
    ) or "<tr><td>none</td><td>0</td></tr>"
    source_rows = "".join(
        "<tr>"
        f"<td>{_e(row['source_key'])}</td>"
        f"<td>{'enabled' if row['enabled'] else 'disabled'}</td>"
        f"<td>{_e(row['promotion_state'])}</td>"
        f"<td>{_e(row['plane'])}</td>"
        "</tr>"
        for row in payload["sources"]
    )
    canonical = payload["canonical"]
    research = payload["research"]
    body = f"""
<p data-schema="{_e(payload['schema_version'])}">Bridge schema: {_e(payload['schema_version'])}</p>
<p data-app-sha="{_e(identity.app_sha)}">App SHA: {_e(identity.app_sha)}</p>
<p data-app-tree="{_e(identity.app_tree)}">App tree: {_e(identity.app_tree)}</p>
<p data-base-sha="{_e(identity.prototype_base_sha)}">Accepted prototype base SHA: {_e(identity.prototype_base_sha)}</p>
<p>Canonical Board DB: {_e(canonical['path'])}</p>
<p>Canonical file sha256 (read-only file hash, not a health signal): {_e(canonical['sha256'])}</p>
<p>Canonical file size bytes: {_e(canonical['size_bytes'])}</p>
<p>Research DB: {_e(research['path'])}</p>
<p>Research file sha256: {_e(research['sha256'])}</p>
<h2>Research lead counts by state</h2>
<p>These counts are research bookkeeping. They are separate from source operational health.</p>
<table><thead><tr><th>State</th><th>Count</th></tr></thead><tbody>{count_rows}</tbody></table>
<h2>Source operational health</h2>
<p data-source-health="UNKNOWN">Source operational health: UNKNOWN. This is not observed by the research GUI.</p>
<p data-coverage="lead-count">Observed research leads: {_e(payload['lead_total'])}. A quiet or empty lead list is not a broken source.</p>
<h2>Source roster</h2>
<p>Enabled sources: {_e(payload['sources_enabled'])}. No promotion or source-enable control is available.</p>
<table><thead><tr><th>Source</th><th>Enabled</th><th>Promotion state</th><th>Plane</th></tr></thead><tbody>{source_rows}</tbody></table>
<h2>Import CNX candidate JSONL</h2>
<form method="post" action="/import">
<label>JSONL path <input name="jsonl" size="80"></label>
<button type="submit">Import into research DB</button>
</form>
<p>Delivery: out of scope for this prototype. No delivery outcome is recorded.</p>
"""
    return _layout("Overview", identity, body)


def leads_page(leads: list[dict[str, Any]], identity: UiIdentity, *, archive: bool) -> str:
    rows = []
    for lead in leads:
        rows.append(
            "<tr>"
            f"<td><a href=\"/leads/{_e(lead['lead_id'])}\">{_e(lead['lead_id'])}</a></td>"
            f"<td>{_e(lead['canonical_oem_name'])}</td>"
            f"<td>{_e(lead['claimed_domain'])}</td>"
            f"<td>{_e(lead['imported_at'])} UTC import time</td>"
            f"<td>{_status(lead['status'])}</td>"
            f"<td>{_status(lead['qualification_state'])}</td>"
            f"<td>{_e(lead['cnx_run_id'])} / {_e(lead['cnx_candidate_id'])}</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr><th>Lead</th><th>OEM</th><th>Claimed first-party domain</th>"
        "<th>Import time (UTC)</th><th>Research state</th><th>Qualification state</th>"
        "<th>CNX run / candidate</th></tr></thead><tbody>"
        + ("".join(rows) or "<tr><td colspan=\"7\">none</td></tr>")
        + "</tbody></table>"
    )
    title = "Recently reviewed" if archive else "Research leads"
    note = (
        "<p>Decided leads stay in this archive. History is not deleted to clear the active queue.</p>"
        if archive
        else "<p>Active queue. Decided leads are hidden here by read-side filtering.</p>"
    )
    return _layout(title, identity, note + table)


def _facts(title: str, rows: list[tuple[str, object]]) -> str:
    body = "".join(f"<tr><th>{_e(name)}</th><td>{_e(value)}</td></tr>" for name, value in rows)
    return f"<h2>{_e(title)}</h2><table>{body}</table>"


def lead_page(lead: dict[str, Any] | None, identity: UiIdentity, *, notice: dict[str, Any] | None = None) -> str:
    if lead is None:
        return _layout("Lead", identity, "<p data-outcome=\"refused\">Lead not found. not committed</p>", notice=notice)
    actions = ""
    if lead["status"] in {"IMPORTED", "QUALIFYING"}:
        actions = f"""
<h2>Operator actions</h2>
<p>Maturity: experimental research action. Sources stay disabled. This does not promote a source.</p>
<form method="post" action="/leads/{_e(lead['lead_id'])}/qualify">
<button type="submit">Qualify with first-party evidence (experimental; sources stay disabled)</button>
</form>
<form method="post" action="/leads/{_e(lead['lead_id'])}/reject">
<label>Reject reason <input name="reason" size="60"></label>
<button type="submit">Reject lead</button>
</form>
"""
    fetches = lead.get("evidence")
    body = (
        _facts("CNX discovery claim (non-authoritative)", [
            ("lead id", lead["lead_id"]),
            ("OEM claim", lead["canonical_oem_name"]),
            ("claimed first-party domain", lead["claimed_domain"]),
            ("catalogue URL", lead["catalogue_url"]),
            ("candidate URLs", lead["candidate_urls"]),
            ("CNX run", lead["cnx_run_id"]),
            ("CNX candidate", lead["cnx_candidate_id"]),
            ("envelope hash", lead["envelope_hash"]),
            ("discovery reason", lead.get("discovery_reason")),
            ("discovery source class", lead.get("discovery_source_class")),
            ("notes", lead.get("notes")),
            ("research state", status_text(lead["status"])),
            ("qualification state", status_text(lead["qualification_state"])),
            ("reason", lead.get("reason")),
        ])
        + _stamp("CNX discovered at", lead.get("discovered_at_utc"))
        + _stamp("Import time", lead.get("imported_at"))
        + _facts("Board independently observed first-party evidence", [
            ("authority", "Board observation outranks the CNX claim when they disagree"),
            ("evidence", fetches if fetches else "no Board observation recorded"),
        ])
        + "<h2>Stored stages</h2>"
        + _stage_table([{"lead": lead, "stages": activity_stages(lead)}])
        + actions
    )
    return _layout(f"Lead {lead['lead_id']}", identity, body, notice=notice)


def _stage_table(rows: list[dict[str, Any]]) -> str:
    rendered = []
    for row in rows:
        lead = row["lead"]
        rendered.append(f"<h3>{_e(lead['lead_id'])} {_status(lead['status'])}</h3>")
        rendered.append("<table><thead><tr><th>Stage</th><th>Outcome</th></tr></thead><tbody>")
        for stage in row["stages"]:
            rendered.append(
                f"<tr><td>{_e(stage['name'])}</td><td data-stage-outcome=\"{_e(stage['outcome'])}\">"
                f"{_e(stage['outcome'])}</td></tr>"
            )
        rendered.append("</tbody></table>")
    return "".join(rendered) or "<p>No qualification runs stored.</p>"


def activity_page(rows: list[dict[str, Any]], identity: UiIdentity) -> str:
    note = (
        "<p>Each stored field stays visible. Fetch HTTP status, disagreement, and research status "
        "are separate outcomes. They stay labeled on their own rows.</p>"
    )
    return _layout("Activity", identity, note + (_stage_table(rows) or "<p>No qualification runs stored.</p>"))


def about_page(payload: dict[str, Any]) -> str:
    identity: UiIdentity = payload["identity"]
    body = f"""
<p data-app-sha="{_e(identity.app_sha)}">Exact app SHA: {_e(identity.app_sha)}</p>
<p data-app-tree="{_e(identity.app_tree)}">Exact app tree: {_e(identity.app_tree)}</p>
<p>Accepted prototype base SHA: {_e(identity.prototype_base_sha)}</p>
<p>Accepted prototype base tree: {_e(identity.prototype_base_tree)}</p>
<p>Canonical Board DB: {_e(payload['canonical']['path'])}</p>
<p>Research DB: {_e(payload['research']['path'])}</p>
<p data-bind="{_e(identity.bind_host)}:{_e(identity.bind_port)}">Bind address: {_e(identity.bind_host)}:{_e(identity.bind_port)}</p>
<p data-standards-tag="{_e(identity.standards_tag)}" data-standards-commit="{_e(identity.standards_commit)}">Standards UI: {_e(identity.standards_tag)} @ {_e(identity.standards_commit)}</p>
<p>Bridge schema: {_e(payload['schema_version'])}</p>
<p>Source enablement: {_e(payload['sources_enabled'])} enabled of {_e(len(payload['sources']))} registered.</p>
<p>Prototype / non-production. Promotion remains explicit governed configuration outside this GUI.</p>
<p>Delivery: out of scope. No delivery state is invented.</p>
<p data-health="UNKNOWN">Runtime and deployment health: UNKNOWN.</p>
"""
    return _layout("About / safety", identity, body)


def outcome_page(identity: UiIdentity, outcome: dict[str, Any]) -> str:
    lead = outcome.get("lead")
    extra = ""
    raw = outcome.get("raw") or {}
    results = raw.get("results") if isinstance(raw, dict) else None
    if isinstance(results, list):
        items = "".join(
            f"<li>{_e(item.get('status'))} {_e(item.get('reason') or '')}</li>" for item in results
        )
        extra = f"<ul>{items}</ul>"
    if lead:
        return lead_page(lead, identity, notice=outcome).replace("</h1>", "</h1>" + extra, 1)
    body = f"<p>{_e(outcome.get('message'))}</p>{extra}<p><a href=\"/leads\">Research leads</a></p>"
    return _layout("Result", identity, body, notice=outcome)
