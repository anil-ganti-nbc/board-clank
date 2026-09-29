"""Command line for the isolated CNX OEM seeder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cnx_seeder.engine import make_clock, make_transport, noop_existing, replay_sample, run_sample
from cnx_seeder.paths import REPO_ROOT, PathGuardError, default_state_dir
from cnx_seeder.report import write_report
from cnx_seeder.revision import RevisionError, resolve_revision
from cnx_seeder.roster import RosterError, default_roster_path
from cnx_seeder.store import open_queue


def _state_dir(value: str | None) -> Path:
    if value:
        return Path(value)
    return default_state_dir(REPO_ROOT)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cnx-oem-seeder")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--state-dir")
    run.add_argument("--run-id", required=True)
    run.add_argument("--code-revision")
    run.add_argument("--roster")
    run.add_argument("--now")
    run.add_argument("--fixture")
    run.add_argument("--live", action="store_true")

    report = sub.add_parser("report")
    report.add_argument("--state-dir")

    replay = sub.add_parser("replay")
    replay.add_argument("--state-dir")
    replay.add_argument("--run-id", required=True)
    replay.add_argument("--code-revision")
    replay.add_argument("--from-run")
    replay.add_argument("--now")
    replay.add_argument("--fixture")
    replay.add_argument("--live", action="store_true")
    return parser


def _revision(flag: str | None, live: bool) -> str:
    return resolve_revision(flag, repo_root=REPO_ROOT, live=live)


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        sha = _revision(args.code_revision, args.live)
    except RevisionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        queue = open_queue(_state_dir(args.state_dir), REPO_ROOT)
    except PathGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        if queue.has_run(args.run_id):
            return noop_existing(queue, args.run_id)
        roster = Path(args.roster) if args.roster else default_roster_path(REPO_ROOT)
        clock = make_clock(args.now, args.live)
        transport = make_transport(Path(args.fixture) if args.fixture else None, args.live)
        from cnx_seeder.http import Fetcher

        fetcher = Fetcher(transport, clock)
        started = clock.now
        return run_sample(
            queue,
            run_id=args.run_id,
            code_revision=sha,
            roster_path=roster,
            fetcher=fetcher,
            started=started,
        )
    except RosterError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        queue.close()


def _cmd_report(args: argparse.Namespace) -> int:
    try:
        queue = open_queue(_state_dir(args.state_dir), REPO_ROOT)
    except PathGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        write_report(queue)
    finally:
        queue.close()
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    try:
        sha = _revision(args.code_revision, args.live)
    except RevisionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        queue = open_queue(_state_dir(args.state_dir), REPO_ROOT)
    except PathGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        if queue.has_run(args.run_id):
            return noop_existing(queue, args.run_id)
        source = args.from_run or queue.latest_completed(args.run_id)
        if not source:
            print("replay source run is missing", file=sys.stderr)
            return 1
        clock = make_clock(args.now, args.live)
        transport = None
        if args.live:
            transport = make_transport(None, True)
        started = clock.now
        return replay_sample(
            queue,
            run_id=args.run_id,
            code_revision=sha,
            source_id=source,
            live=args.live,
            started=started,
            transport=transport,
            clock=clock,
        )
    except RosterError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        queue.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.live and args.fixture:
            print("pass either --live or --fixture", file=sys.stderr)
            return 2
        return _cmd_run(args)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "replay":
        if args.live and args.fixture:
            print("pass either --live or --fixture", file=sys.stderr)
            return 2
        if not args.live and not args.fixture:
            print("replay requires --fixture or --live", file=sys.stderr)
            return 2
        return _cmd_replay(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
