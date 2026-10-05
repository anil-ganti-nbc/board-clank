"""Manual operator commands. They never write the canonical Board database."""

from __future__ import annotations

import json

from board_clank.research.bridge import import_jsonl, qualify_lead, reject_lead
from board_clank.research.export import export_jsonl, synthetic_envelope
from board_clank.research.paths import same_database
from board_clank.research.store import ResearchStore, ResearchStoreError


def _emit(payload: dict, code: int) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return code


def _same_database(research_db: str, canonical_db: str | None) -> bool:
    return same_database(research_db, canonical_db)


def cmd_export(args) -> int:
    envelopes = [synthetic_envelope(args.run)]
    try:
        count = export_jsonl(args.output, envelopes, run_id=args.run)
    except FileExistsError as exc:
        return _emit({"status": "refused", "reason": str(exc)}, 2)
    return _emit({"status": "exported", "run_id": args.run, "output": args.output, "count": count}, 0)


def cmd_import(args) -> int:
    if not args.research_only:
        return _emit({"status": "refused", "reason": "research_only_required"}, 2)
    if _same_database(args.research_db, args.db):
        return _emit({"status": "refused", "reason": "research_db_must_not_be_canonical_db"}, 2)
    try:
        with ResearchStore(args.research_db) as store:
            report = import_jsonl(store, args.input)
    except (OSError, ResearchStoreError) as exc:
        return _emit({"status": "refused", "reason": str(exc)}, 2)
    return _emit(report, report["exit_code"])


def _with_store(args, action):
    if _same_database(args.research_db, getattr(args, "db", None)):
        return _emit({"status": "refused", "reason": "research_db_must_not_be_canonical_db"}, 2)
    try:
        with ResearchStore(args.research_db) as store:
            result = action(store)
    except (OSError, ResearchStoreError) as exc:
        return _emit({"status": "refused", "reason": str(exc)}, 2)
    return _emit(result if isinstance(result, dict) else {"leads": result}, result["exit_code"] if isinstance(result, dict) and "exit_code" in result else 0)


def cmd_list(args) -> int:
    def action(store: ResearchStore) -> dict:
        return {"exit_code": 0, "leads": store.list_leads()}
    return _with_store(args, action)


def cmd_show(args) -> int:
    def action(store: ResearchStore) -> dict:
        row = store.lead(args.lead_id)
        if row is None:
            return {"exit_code": 2, "status": "missing", "reason": "unknown_lead", "lead_id": args.lead_id}
        from board_clank.research.bridge import _public_lead
        return {"exit_code": 0, "lead": _public_lead(row)}
    return _with_store(args, action)


def cmd_qualify(args) -> int:
    return _with_store(args, lambda store: qualify_lead(store, args.lead_id))


def cmd_reject(args) -> int:
    return _with_store(args, lambda store: reject_lead(store, args.lead_id, args.reason))
