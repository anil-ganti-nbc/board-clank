"""board-clank CLI. No production scheduler. No Discord send."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from board_clank._version import (
    CLANK_ID,
    EXPECTED_SCHEMA_VERSION,
    FIRST_SEEN_LAW,
    IDENTITY_LAW,
    PACKAGE_VERSION,
    RELEASE_CHANNEL,
    SOURCE_REVISION,
)
from board_clank.collectors.mock import FixtureCollector, get_adapter
from board_clank.collectors.raspberry_pi import SOURCE_KEY as RPI_SOURCE_KEY
from board_clank.compatibility import StateCompatibilityError, inspect_path
from board_clank.health import health_payload
from board_clank.paths import default_db_path
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources, sync_sources_to_store
from board_clank.store import Store
from board_clank.taxonomy import CompatibilityState


def _json(payload: object) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _open_store(path: str | None, *, migrate: bool) -> Store:
    target = path or str(default_db_path())
    return Store(target, migrate=migrate)


def cmd_version(_: argparse.Namespace) -> int:
    return _json(
        {
            "clank_id": CLANK_ID,
            "version": PACKAGE_VERSION,
            "release_channel": RELEASE_CHANNEL,
            "source_revision": SOURCE_REVISION,
            "schema_version": EXPECTED_SCHEMA_VERSION,
        }
    )


def cmd_identity(_: argparse.Namespace) -> int:
    return _json(
        {
            "clank_id": CLANK_ID,
            "identity_law": IDENTITY_LAW,
            "first_seen_law": FIRST_SEEN_LAW,
            "hierarchy": ["Vendor", "Family", "Board", "BoardRevision", "BoardVariant"],
            "sku_is_not_board": True,
            "revision_is_not_product_name": True,
            "first_seen_is_not_market_novelty": True,
        }
    )


def cmd_health(args: argparse.Namespace) -> int:
    payload = health_payload(args.db)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ok" else 1


def cmd_check_state(args: argparse.Namespace) -> int:
    report = inspect_path(args.db or default_db_path())
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    if report.state in {CompatibilityState.FRESH, CompatibilityState.COMPATIBLE, CompatibilityState.MIGRATION_REQUIRED}:
        return 0
    return 3


def cmd_migrate(args: argparse.Namespace) -> int:
    try:
        store = _open_store(args.db, migrate=True)
        sync_sources_to_store(store)
        report = inspect_path(store.path)
        store.close()
    except StateCompatibilityError as exc:
        print(json.dumps({"status": "state_incompatible", "gate": "persistent_state_compatibility", **exc.report.as_dict()}, indent=2))
        return 3
    return _json({"status": "migrated", "compatibility": report.as_dict()})


def cmd_status(args: argparse.Namespace) -> int:
    try:
        store = _open_store(args.db, migrate=False)
    except StateCompatibilityError as exc:
        if exc.report.state is CompatibilityState.FRESH:
            return _json({"status": "fresh", "boards": 0, "events": 0, "runs": 0})
        print(json.dumps({"status": "state_incompatible", **exc.report.as_dict()}, indent=2))
        return 3
    payload = {
        "status": "ok",
        "vendors": store.count("vendors"),
        "boards": store.count("boards"),
        "revisions": store.count("board_revisions"),
        "variants": store.count("board_variants"),
        "socs": store.count("socs"),
        "events": store.count("events"),
        "notifications": store.count("notifications"),
        "runs": store.count("collector_runs"),
        "receipts": store.count("processed_run_receipts"),
        "occurrences": store.count("observation_occurrences"),
    }
    store.close()
    return _json(payload)


def cmd_sources(args: argparse.Namespace) -> int:
    records = [row.model_dump() for row in load_sources()]
    if args.assert_foundation:
        assert_foundation_0_roster()
    return _json({"count": len(records), "promoted": 0, "sources": records})


def cmd_events(args: argparse.Namespace) -> int:
    store = _open_store(args.db, migrate=False)
    rows = store.all("SELECT event_key, event_type, entity_key, baseline_silent, source_key FROM events ORDER BY event_id")
    store.close()
    return _json([dict(row) for row in rows])


def cmd_notifications(args: argparse.Namespace) -> int:
    store = _open_store(args.db, migrate=False)
    rows = store.all("SELECT event_key, disposition, channel, delivered_at FROM notifications ORDER BY notification_id")
    store.close()
    return _json([dict(row) for row in rows])


def cmd_report(args: argparse.Namespace) -> int:
    store = _open_store(args.db, migrate=False)
    boards = store.all(
        """
        SELECT b.board_key, b.marketing_name, b.board_type, COUNT(v.variant_key) AS variants
        FROM boards b
        LEFT JOIN board_variants v ON v.board_key = b.board_key
        GROUP BY b.board_key
        ORDER BY b.board_key
        """
    )
    store.close()
    return _json({"boards": [dict(row) for row in boards]})


def cmd_baseline_status(args: argparse.Namespace) -> int:
    try:
        store = _open_store(args.db, migrate=False)
    except StateCompatibilityError as exc:
        if exc.report.state is CompatibilityState.FRESH:
            return _json({"baselines": []})
        print(json.dumps({"status": "state_incompatible", **exc.report.as_dict()}, indent=2))
        return 3
    rows = store.all("SELECT source_key, baseline_run_id, established_at, observation_count FROM source_baselines")
    store.close()
    return _json({"baselines": [dict(row) for row in rows]})


def cmd_collect(args: argparse.Namespace) -> int:
    if args.live:
        print(json.dumps({"status": "refused", "reason": "live collection is disabled in Foundation 0"}))
        return 2
    experimental_live = bool(getattr(args, "experimental_live", False))
    try:
        adapter = get_adapter(
            args.source,
            experimental_live=experimental_live,
            corpus=getattr(args, "corpus", None) or "baseline",
        )
    except KeyError:
        # Fail closed: unknown or unregistered source, never a crash.
        print(json.dumps({"status": "refused", "reason": f"no adapter registered for {args.source}"}))
        return 2
    if experimental_live and not getattr(type(adapter), "supports_experimental_live", False):
        print(json.dumps({"status": "refused", "reason": f"experimental live is not implemented for {args.source}"}))
        return 2
    store = _open_store(args.db, migrate=True)
    sync_sources_to_store(store)
    pipeline = Pipeline(store)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if args.fixture:
        requests = FixtureCollector(args.fixture).collect_runs()
        results = [pipeline.accept_run(req).as_dict() for req in requests]
        store.close()
        return _json({"mode": "fixture", "results": results})
    if experimental_live:
        mode = "experimental-live"
    elif args.source == RPI_SOURCE_KEY:
        mode = "rpi-fixture"
    elif hasattr(adapter, "corpus"):
        mode = "corpus-fixture"
    else:
        mode = "inert"
    result = pipeline.accept_run(adapter.collect(args.run_id or f"{mode}-{args.source}", now))
    store.close()
    return _json({"mode": mode, "result": result.as_dict(), "delivery_eligible": False, "promoted": False})


def cmd_source_intel(args: argparse.Namespace) -> int:
    try:
        store = _open_store(args.db, migrate=False)
    except StateCompatibilityError as exc:
        if exc.report.state is CompatibilityState.FRESH:
            return _json({"source_key": args.source, "attempts": [], "baselines": [], "delivery_eligible": False})
        print(json.dumps({"status": "state_incompatible", **exc.report.as_dict()}, indent=2))
        return 3
    source = args.source
    runs = store.all(
        """
        SELECT run_id, source_key, collector_key, started_at, finished_at, status, fixture_scenario, error
        FROM collector_runs WHERE source_key = ? ORDER BY started_at
        """,
        (source,),
    )
    baseline = store.one("SELECT source_key, baseline_run_id, established_at, observation_count FROM source_baselines WHERE source_key = ?", (source,))
    events = store.all(
        "SELECT event_type, COUNT(*) AS n FROM events WHERE source_key = ? GROUP BY event_type ORDER BY event_type",
        (source,),
    )
    errors = store.all("SELECT message, created_at FROM run_errors WHERE source_key = ? ORDER BY error_id", (source,))
    src = store.one("SELECT enabled, promotion_state FROM sources WHERE source_key = ?", (source,))
    diagnostics = store.all(
        """
        SELECT diagnostic_type, status, COUNT(*) AS conditions
        FROM diagnostic_conditions
        WHERE source_key = ?
        GROUP BY diagnostic_type, status
        ORDER BY diagnostic_type, status
        """,
        (source,),
    )
    store.close()
    last_ok = next((dict(row) for row in reversed(runs) if row["status"] == "accepted"), None)
    last_attempt = dict(runs[-1]) if runs else None
    return _json(
        {
            "source_key": source,
            "operational_health_separate": True,
            "delivery_eligible": False,
            "enabled": bool(src["enabled"]) if src else False,
            "promotion_state": src["promotion_state"] if src else "EXPERIMENTAL",
            "last_attempted": last_attempt,
            "last_succeeded": last_ok,
            "baseline": dict(baseline) if baseline else None,
            "event_counts": [dict(row) for row in events],
            "diagnostic_conditions": [dict(row) for row in diagnostics],
            "parser_or_source_errors": [dict(row) for row in errors],
            "attempts": [dict(row) for row in runs],
        }
    )


def cmd_backup(args: argparse.Namespace) -> int:
    from board_clank.backup import BackupError, create_backup

    try:
        result = create_backup(args.db, args.out, name=args.name)
    except BackupError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, indent=2))
        return 3
    return _json({"status": "backed_up", **result.as_dict()})


def cmd_restore(args: argparse.Namespace) -> int:
    from board_clank.backup import BackupError, restore_backup

    try:
        report = restore_backup(
            args.backup_file,
            args.metadata,
            args.target,
            activate=args.activate,
            force=args.force,
        )
    except BackupError as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, indent=2))
        return 3
    status = "restored_activated" if report["activated"] else "restored_staging"
    return _json({"status": status, **report})


def cmd_manifest(args: argparse.Namespace) -> int:
    from board_clank.manifest import ManifestError, build_manifest, validate_manifest

    try:
        report = validate_manifest(build_manifest())
    except ManifestError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 3
    return _json(report)


def cmd_observe(args: argparse.Namespace) -> int:
    from board_clank import observer

    target = args.db or str(default_db_path())
    return _json(observer.full_snapshot(target))


def cmd_manifest_declared(args: argparse.Namespace) -> int:
    from board_clank.manifest import ManifestError, load_manifest, validate_manifest

    try:
        manifest = load_manifest(args.file) if args.file else load_manifest()
        report = validate_manifest(manifest)
    except ManifestError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 3
    return _json(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="board-clank")
    parser.add_argument("--db", help="SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    sub.add_parser("identity")
    sub.add_parser("health")
    sub.add_parser("status")
    sub.add_parser("events")
    sub.add_parser("notifications")
    sub.add_parser("report")
    sub.add_parser("baseline-status")
    sources = sub.add_parser("sources")
    sources.add_argument("--assert-foundation", action="store_true")
    sub.add_parser("check-state")
    sub.add_parser("migrate")
    collect = sub.add_parser("collect")
    collect.add_argument("--fixture")
    collect.add_argument("--source", default="raspberry-pi-product")
    collect.add_argument("--run-id")
    collect.add_argument("--live", action="store_true")
    collect.add_argument(
        "--experimental-live",
        action="store_true",
        help="Manual opt-in network fetch for live-capable sources only. Never used by tests.",
    )
    collect.add_argument("--corpus", default="baseline", help="Offline Raspberry Pi fixture corpus name")
    intel = sub.add_parser("source-intel")
    intel.add_argument("--source", default="raspberry-pi-product")
    backup = sub.add_parser("backup", help="Operator-triggered verified backup of persistent state")
    backup.add_argument("--out", required=True, help="Output directory for the artifact pair")
    backup.add_argument("--name", help="Optional artifact stem (default: <db stem>-<UTC timestamp>)")
    restore = sub.add_parser("restore", help="Restore a verified backup into an explicit target")
    restore.add_argument("--backup-file", required=True, help="Backup database image path")
    restore.add_argument("--metadata", required=True, help="Backup sidecar metadata JSON path")
    restore.add_argument("--target", required=True, help="Explicit operator target database path")
    restore.add_argument("--activate", action="store_true", help="Replace the target with the verified restore")
    restore.add_argument("--force", action="store_true", help="Allow replacing an existing target")
    sub.add_parser("manifest", help="Validate and emit the Board Clank manifest report")
    manifest_cmd = sub.add_parser("manifest-declared", help="Validate the committed declaration manifest")
    manifest_cmd.add_argument("--file", help="Optional declaration path (default: bundled manifest.json)")
    sub.add_parser("observe", help="Read-only observer surface snapshot (v0.2 contract)")
    return parser


COMMANDS = {
    "version": cmd_version,
    "identity": cmd_identity,
    "health": cmd_health,
    "status": cmd_status,
    "sources": cmd_sources,
    "events": cmd_events,
    "notifications": cmd_notifications,
    "report": cmd_report,
    "baseline-status": cmd_baseline_status,
    "check-state": cmd_check_state,
    "migrate": cmd_migrate,
    "collect": cmd_collect,
    "source-intel": cmd_source_intel,
    "backup": cmd_backup,
    "restore": cmd_restore,
    "manifest": cmd_manifest,
    "manifest-declared": cmd_manifest_declared,
    "observe": cmd_observe,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except StateCompatibilityError as exc:
        print(
            json.dumps(
                {
                    "status": "state_incompatible",
                    "gate": "persistent_state_compatibility",
                    **exc.report.as_dict(),
                },
                indent=2,
            )
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
