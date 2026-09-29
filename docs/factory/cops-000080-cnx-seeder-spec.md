# SPEC — COPS-000080 CNX OEM discovery seeder

| Field | Value |
| --- | --- |
| Mission | COPS-000080 |
| Phase of this document | SPEC v3 (rework of `b8c893951ef7e0169d11cab3c8e201a57d220a00`) |
| Target | `anil-ganti-nbc/board-clank` |
| Development base | `production-readiness-1b-odroid-coverage` at `613c3a13c0e52088eeb33d6266b6ca7b2b783000` |
| Spec branch | `factory/cops-000080-cnx-seeder` |
| Contract | Frozen project contract v1, sha256 `a7c2f1d10d0bf427642c437362446165bb519adf7c05a95f7a980d0558f53456` (verbatim in the appendix; not modified) |
| This file | Spec only. No seeder code, tests, config, schema, CI, or operational change. |
| Sample source | Prefer `https://www.cnx-software.com/news/sbc/feed/`. HTML fallback `https://www.cnx-software.com/news/sbc/`. |
| Source plane / authority | `DISCOVERY_ONLY` / `THIRD_PARTY_DISCOVERY` — stored only inside the seeder queue, never in Board's registry |

CNX Software is an external knowledgebase. A bounded sample of its SBC news may expose OEM leads and must retain discovery provenance. CNX must never enter Board's operational source registry, product or event collector, canonical URL, observation or novelty evidence, editorial notification, Discord, or outbox path.

No candidate is admitted to production collection by this design. `promotion_freeze: true`, every `enabled: false` flag, the six active first-party sources, the nine inactive phase-two placeholders, and the Jetson out-of-scope decision stay as they are on the base commit.

Webpage text from CNX and from OEM sites is untrusted data. The seeder must not follow instructions embedded in it. A design-context read of `https://www.cnx-software.com/robots.txt` returned HTTP 200. A design-context GET of the SBC listing from the Cursor VM returned HTTP 403, and that body was not used. The coordinator's Windows host gets HTTP 200 on `/news/sbc/` and `/news/sbc/feed/`, and robots.txt allows those paths for `User-agent: *`. The acceptance run is executed on that Windows host, not by retrying the VM with a different user agent. Those facts are design context. They are not a reason to bypass robots.txt or a block.

The seeder process must run on Windows and on Linux. Every path is a `pathlib.Path`. The package must not call `subprocess`, `os.system`, `fcntl`, `msvcrt`, `pty`, or `posix`, and it must not shell out to `git`, `sh`, or `cmd`. Reading `.git/HEAD` is a `Path.read_text` of files, described in section 3.4.

## 1. Verified base this spec is bound to

Checked on this worktree before the branch was created:

- `HEAD` and `origin/production-readiness-1b-odroid-coverage` are both `613c3a13c0e52088eeb33d6266b6ca7b2b783000`.
- `origin/main` is `ca96231159ac787c9ec1cc1eb447772489db8cfd` and has no merge base with this lineage. Any later pull request must target `production-readiness-1b-odroid-coverage`. This SPEC task does not open a pull request.
- `config/sources.yaml` and `src/board_clank/sources.yaml` are byte-identical. sha256 `ba2a5bc4a25f4b7836b7ec99b9c7dfdee5593bd863a6cacb63f4a710339fd6ab`.
- Registry meta: `foundation: 0`, `promotion_freeze: true`, `live_collection: false`, `jetson_scope: out-of-scope-pending-decision`. All sixteen source entries have `enabled: false`.
- Loader preference (`src/board_clank/sources.py`): `config/sources.yaml` when that file exists, otherwise the packaged copy. `sync_sources_to_store` upserts the roster into the operational `sources` table. The seeder must not call it.
- Operational DB path (`src/board_clank/paths.py`): `$BOARD_CLANK_DB`, else `$BOARD_CLANK_DATA_DIR/board_clank.db`, else `/app/data/board_clank.db` when that directory exists, else `<repo>/data/board_clank.db`. `board_clank.store.Store` auto-migrates on open. The seeder must not instantiate it.
- Full suite at this base: `pytest -q` with `testpaths = ["tests"]` and `pythonpath = ["src"]` (`pyproject.toml`), run under the black-hole proxy from `.github/workflows/ci.yml` (`HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` set to `http://127.0.0.1:9`, `NO_PROXY=127.0.0.1,localhost,::1`), plus `board-clank sources --assert-foundation`.
- Push CI does not list `factory/*`. A green check on a future pull request is not deployment proof.
- `docker-compose.yml` runs the `board-clank` image with command `health` and volume `board-clank-data` at `/app/data`. The manifest requires `scheduler_authority: NONE` and `notification_authority: NONE`.

Roster of record (read-only; placeholders have `base_urls: []`):

| Role | source_key | vendor | `base_urls` host after stripping one leading `www.` |
| --- | --- | --- | --- |
| Active | `raspberry-pi-product` | `raspberry-pi` | `raspberrypi.com` |
| Active | `orange-pi-product` | `orange-pi` | `orangepi.org` |
| Active | `radxa-product` | `radxa` | `radxa.com` |
| Active | `banana-pi-product` | `banana-pi` | `banana-pi.org` |
| Active | `hardkernel-odroid-product` | `hardkernel-odroid` | `hardkernel.com` |
| Active | `pine64-product` | `pine64` | `pine64.org` |
| Placeholder | `friendlyelec-placeholder` | `friendlyelec` | none (`base_urls: []`) |
| Placeholder | `milk-v-placeholder` | `milk-v` | none |
| Placeholder | `beagleboard-placeholder` | `beagleboard` | none |
| Placeholder | `libre-computer-placeholder` | `libre-computer` | none |
| Placeholder | `khadas-placeholder` | `khadas` | none |
| Placeholder | `up-board-placeholder` | `up-board` | none |
| Placeholder | `seeed-studio-placeholder` | `seeed-studio` | none |
| Placeholder | `firefly-placeholder` | `firefly` | none |
| Placeholder | `lattepanda-placeholder` | `lattepanda` | none |
| Out of scope | `nvidia-jetson-out-of-scope` | `nvidia-jetson` | none |

## 2. Separate CLI and isolated queue

BUILD adds one new package and one new console script. It does not add a subcommand to `board-clank`.

| Item | Design |
| --- | --- |
| Package | `src/cnx_seeder/` (not a submodule of `board_clank`) |
| Console script | `cnx-oem-seeder` → `cnx_seeder.cli:main`. Handoff commands invoke `python -m cnx_seeder.cli` so the same entry works on Windows and Linux. |
| Commands | `run`, `report`, `replay` |
| Dependencies | Python 3.12 stdlib plus PyYAML, already locked. No new package, no lockfile edit. |
| State directory | `$CNX_SEEDER_STATE_DIR` or `--state-dir`. Default is `repo_root / "var" / "cnx-seeder"` via `pathlib`. BUILD gitignores that directory. |
| Queue file | `state_dir / "queue.sqlite"` |
| Report | `state_dir / "report.json"` |
| Fetch log export | `state_dir / "fetch-log.jsonl"` (derived from the SQLite `fetches` table; not a second source of truth) |

`queue.sqlite` uses its own schema, created with `sqlite3` inside `cnx_seeder`. It is not a Board migration, it is not opened by `board_clank.store.Store`, and it does not contain `sources`, `events`, `notifications`, `canonical_observations`, or `novelty_evidence`.

### 2.1 Commands

```
python -m cnx_seeder.cli run --state-dir DIR --run-id ID --code-revision SHA [--roster PATH] [--now ISO8601] [--fixture DIR]
python -m cnx_seeder.cli run --state-dir DIR --run-id ID --code-revision SHA --live [--roster PATH]
python -m cnx_seeder.cli report --state-dir DIR
python -m cnx_seeder.cli replay --state-dir DIR --run-id NEW_ID --code-revision SHA [--from-run SOURCE_ID] (--fixture DIR | --live)
```

- `--roster` defaults to `config/sources.yaml` and is opened read-only.
- `--run-id` is required and is the only run identifier. The process does not invent one from the clock.
- `--code-revision` is the full git SHA of the code being run (section 3.4). `$CNX_SEEDER_CODE_REVISION` is used only when the flag is omitted. If both are set they must be identical.
- `--now` is required for deterministic fixture runs. Live runs use UTC time.
- Default mode is fixture. `--live` is the only network mode. Tests never pass `--live` except the revision-gate test, which must fail before any socket.
- There is no admit, enable, promote, collect, or sync command.

### 2.2 What the package must not import

`src/cnx_seeder/**/*.py` must not import `board_clank` at all. In particular it must not import:

- `board_clank.pipeline`
- `board_clank.store`
- `board_clank.policy`
- `board_clank.observer`
- `board_clank.collectors` (any submodule)
- `board_clank.sources` (`load_sources` and `sync_sources_to_store` included)
- `board_clank.cli`, `board_clank.backup`, `board_clank.health`, `board_clank.paths`

`src/board_clank/**/*.py` must not import `cnx_seeder`. The operational CLI stays on the collector, pipeline, and store path it has at `613c3a13`.

Roster loading is a seeder-local read of YAML (`yaml.safe_load` of the file bytes). The seeder does not call `sync_sources_to_store` and does not write either copy of `sources.yaml`.

The copied operational-path function lives in `cnx_seeder.paths` and must not import `board_clank.paths`. Test 37 imports both modules and compares their results.

### 2.3 Path guard

Before any `sqlite3.connect`, resolve `--state-dir` with `Path.resolve(strict=False)` and refuse with a non-zero exit if any of the following is true:

1. The resolved directory, or `queue.sqlite` inside it, is equal to the operational DB path computed by the same rules as `default_db_path` (section 2.5). The seeder duplicates those rules in its own module. It does not import `board_clank.paths`.
2. The resolved path is inside `repo_root / "data"`, `Path("/app/data")`, or `$BOARD_CLANK_DATA_DIR`.
3. Any path component or final file name equals `board_clank.db`.
4. The path is the config file `config/sources.yaml` or `src/board_clank/sources.yaml`.

On refusal the seeder creates no file and does not open SQLite. A missing operational DB stays missing. The guard is not a warning.

### 2.4 Mechanical enforcement

BUILD ships `tests/test_cnx_seeder_isolation.py` which does all of the following, and does not treat a boolean helper as the evidence:

1. Parse every `src/cnx_seeder/**/*.py` file with `ast` and fail if any import's top-level module is `board_clank`, or if the source contains the name `sync_sources_to_store`.
2. Parse every `src/board_clank/**/*.py` file and fail if any import's top-level module is `cnx_seeder`.
3. The same AST walk fails if `cnx_seeder` imports `subprocess`, `fcntl`, `msvcrt`, `pty`, or `posix`.
4. Point `--state-dir` at the operational DB path and at `repo_root / "data" / "board_clank.db"`. Assert a non-zero exit, an unchanged sha256 if the file already existed, and that the file was not created if it did not.
5. Run a fixture seeder run. Assert sha256 of both `sources.yaml` copies is unchanged and still equal, and that a pre-seeded operational SQLite (opened only by the test, via `BOARD_CLANK_DB` set to a temp file the seeder is not allowed to use) has identical per-table counts and identical ordered-row hashes for every table in `board_clank.compatibility.EXPECTED_TABLES`. The test computes those hashes itself.
6. Open `queue.sqlite` read-only in the test and assert the names `events`, `notifications`, `sources`, `canonical_observations`, and `novelty_evidence` are absent from `sqlite_master`.

### 2.5 Copied operational DB path

`cnx_seeder.paths.operational_db_path(repo_root)` implements the rules in `src/board_clank/paths.py` at `613c3a13`, using `pathlib` and `os.environ` only:

1. If `BOARD_CLANK_DB` is set and non-empty, that value is the path.
2. Else if `BOARD_CLANK_DATA_DIR` is set and non-empty, the path is that directory joined with `board_clank.db`.
3. Else if `Path("/app/data").exists()`, the path is `Path("/app/data") / "board_clank.db"`.
4. Else the path is `repo_root / "data" / "board_clank.db"`.

`repo_root` is `Path(__file__).resolve().parents[2]` for a module at `src/cnx_seeder/`. Test 37 checks this function against `board_clank.paths.default_db_path` under the same environment. A drift between the two fails the test.

## 3. Data model

Schema version `1` lives only inside `cnx_seeder` (a SQL string in the package). It is not added under `migrations/` and it is not applied to Board's database.

`cnx_article_url` and `primary_url` are different columns. A qualified row requires both, and a `CHECK` requires they differ. `primary_url` is the first-party board/product surface (product page, datasheet, or spec page). `homepage_url` is the verified homepage or company/about evidence URL and is stored as its own column. The CNX article URL is discovery provenance only. Neither `primary_url` nor `homepage_url` may use a CNX host (section 6.4).

`article_title` is the raw title string. It is not the vendor name. `discovered_name` and `normalized_name` are the extracted subject vendor (section 6.1).

### 3.1 Tables

```sql
CREATE TABLE seeder_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- required keys: schema_version=1, alias_table_version, source_plane=DISCOVERY_ONLY,
-- source_authority=THIRD_PARTY_DISCOVERY

CREATE TABLE runs (
    run_id               TEXT PRIMARY KEY,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    code_revision        TEXT NOT NULL,
    alias_table_version  TEXT NOT NULL,
    roster_sha256        TEXT NOT NULL,
    sample_source        TEXT NOT NULL, -- feed or html
    listing_url          TEXT NOT NULL,
    sample_window_start  TEXT,
    sample_window_end    TEXT,
    article_urls_json    TEXT NOT NULL,
    max_listing_pages    INTEGER NOT NULL,
    max_articles         INTEGER NOT NULL,
    status               TEXT NOT NULL,
    CHECK (length(code_revision) = 40)
);

CREATE TABLE fetches (
    fetch_id        INTEGER PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    url             TEXT NOT NULL,
    attempt         INTEGER NOT NULL, -- 1 = first try, 2 = the single retry
    fetched_at      TEXT NOT NULL,
    http_status     INTEGER,
    content_sha256  TEXT,
    byte_length     INTEGER,
    elapsed_ms      INTEGER,
    robots_decision TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    error           TEXT,
    UNIQUE (run_id, url, attempt)
);

CREATE TABLE leads (
    lead_key                  TEXT PRIMARY KEY,
    cnx_article_url           TEXT NOT NULL,
    article_title             TEXT NOT NULL,
    discovered_name           TEXT NOT NULL,
    normalized_name           TEXT NOT NULL,
    comparison_mentions_json  TEXT NOT NULL,
    classification            TEXT NOT NULL,
    reason_code               TEXT NOT NULL,
    primary_url               TEXT,
    primary_domain            TEXT,
    primary_host              TEXT,
    homepage_url              TEXT,
    homepage_host             TEXT,
    board_surface_url         TEXT,
    qualified                 INTEGER NOT NULL DEFAULT 0 CHECK (qualified IN (0, 1)),
    CHECK (primary_url IS NULL OR primary_url <> cnx_article_url),
    CHECK (homepage_url IS NULL OR homepage_url <> cnx_article_url)
);

CREATE TABLE lead_sightings (
    run_id    TEXT NOT NULL REFERENCES runs(run_id),
    lead_key  TEXT NOT NULL REFERENCES leads(lead_key),
    seen_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, lead_key)
);

CREATE TABLE article_sightings (
    run_id           TEXT NOT NULL REFERENCES runs(run_id),
    candidate_key    TEXT NOT NULL,
    cnx_article_url  TEXT NOT NULL,
    seen_at          TEXT NOT NULL,
    PRIMARY KEY (run_id, candidate_key, cnx_article_url)
);

CREATE TABLE qualified_candidates (
    candidate_key      TEXT PRIMARY KEY,
    first_run_id       TEXT NOT NULL,
    cnx_article_url    TEXT NOT NULL,
    article_title      TEXT NOT NULL,
    primary_url        TEXT NOT NULL,
    primary_domain     TEXT NOT NULL,
    primary_host       TEXT NOT NULL,
    homepage_url       TEXT NOT NULL,
    homepage_host      TEXT NOT NULL,
    board_surface_url  TEXT NOT NULL,
    normalized_name    TEXT NOT NULL,
    inserted_at        TEXT NOT NULL,
    content_sha256     TEXT NOT NULL,
    CHECK (primary_url <> cnx_article_url),
    CHECK (homepage_url <> cnx_article_url),
    CHECK (board_surface_url = primary_url),
    CHECK (length(cnx_article_url) > 0),
    CHECK (length(primary_url) > 0),
    CHECK (length(homepage_url) > 0),
    CHECK (primary_host <> 'cnx-software.com'),
    CHECK (homepage_host <> 'cnx-software.com'),
    CHECK (primary_domain <> 'cnx-software.com'),
    CHECK (primary_host NOT LIKE '%.cnx-software.com'),
    CHECK (homepage_host NOT LIKE '%.cnx-software.com'),
    CHECK (primary_domain NOT LIKE '%.cnx-software.com')
);

CREATE TRIGGER qualified_reject_cnx
BEFORE INSERT ON qualified_candidates
FOR EACH ROW
WHEN NEW.primary_host = 'cnx-software.com'
  OR NEW.primary_host LIKE '%.cnx-software.com'
  OR NEW.homepage_host = 'cnx-software.com'
  OR NEW.homepage_host LIKE '%.cnx-software.com'
  OR NEW.primary_domain = 'cnx-software.com'
  OR NEW.primary_domain LIKE '%.cnx-software.com'
BEGIN
  SELECT RAISE(ABORT, 'cnx host is discovery provenance only');
END;

CREATE TRIGGER leads_reject_cnx_primary
BEFORE INSERT ON leads
FOR EACH ROW
WHEN (NEW.primary_host IS NOT NULL AND (NEW.primary_host = 'cnx-software.com' OR NEW.primary_host LIKE '%.cnx-software.com'))
  OR (NEW.homepage_host IS NOT NULL AND (NEW.homepage_host = 'cnx-software.com' OR NEW.homepage_host LIKE '%.cnx-software.com'))
  OR (NEW.primary_domain IS NOT NULL AND (NEW.primary_domain = 'cnx-software.com' OR NEW.primary_domain LIKE '%.cnx-software.com'))
BEGIN
  SELECT RAISE(ABORT, 'cnx host is discovery provenance only');
END;
```

Host columns store the parsed hostname only: lowercase, one leading `www.` removed, port removed, trailing dot removed. They are not a substring of the whole URL. `notcnx-software.com` does not match the `LIKE '%.cnx-software.com'` guard, because the pattern requires a dot before `cnx-software.com`.

The application insert path calls `is_cnx_host` (section 6.4) and raises before `INSERT`. The triggers are a second guard so a direct write into `queue.sqlite` still fails. Tests cover both.

Provenance columns, and where they live:

| Fact | Stored on |
| --- | --- |
| Fetch timestamp | `fetches.fetched_at`; run span on `runs.started_at` / `runs.finished_at` |
| HTTP status | `fetches.http_status` (null when the request was not sent, for example robots disallow) |
| Attempt | `fetches.attempt` |
| Content hash | `fetches.content_sha256` = sha256 of the raw response bytes actually retained; `qualified_candidates.content_sha256` copies the hash of the board-surface response |
| Sample window | `runs.sample_window_start` / `sample_window_end` from feed `pubDate` or listing `<time datetime>` when present, otherwise null; `runs.article_urls_json` is the ordered URL list actually taken; `runs.sample_source` is `feed` or `html` |
| Run id | `runs.run_id`, required CLI argument, referenced by fetches and sightings |
| Code revision | `runs.code_revision`, the full 40-hex git SHA from section 3.4. `UNKNOWN` is not a legal value. |
| Alias table version | `runs.alias_table_version` = `known-vendors-1` |
| Roster digest | `runs.roster_sha256` of the bytes actually read |
| Homepage evidence | `homepage_url` on the lead and on the qualified row |
| Extra articles for one OEM | `article_sightings` rows pointing at the same `candidate_key` |

Keys:

- `lead_key` = hex sha256 of `alias_table_version + "\n" + cnx_article_url + "\n" + normalized_name`.
- `candidate_key` = hex sha256 of `alias_table_version + "\n" + normalized_vendor_name + "\n" + resolved_primary_registrable_domain`.

`normalized_vendor_name` is `normalized_name` after section 6.1. `resolved_primary_registrable_domain` is `registrable_domain` (section 4) of the final host after redirects. The article title is not an input to `candidate_key`.

One OEM across several CNX articles is one `qualified_candidates` row. Each article adds an `article_sightings` row `(run_id, candidate_key, cnx_article_url)`. A later article does not insert a second qualified row and does not change the first row's `cnx_article_url`, `primary_url`, or `homepage_url`.

A repeated `--run-id` is a no-op: if `runs.run_id` already exists, the command prints the existing summary and inserts nothing.

`qualified` is 1 only when `classification = board_maker`, `reason_code = qualified`, and `primary_url`, `primary_domain`, `homepage_url`, and `board_surface_url` are all set. The qualified table is the candidate queue. Every other classification stays in `leads` with `qualified = 0` and a non-empty `reason_code`.

### 3.2 Report

`report.json` is canonical JSON: UTF-8, `sort_keys=True`, LF newlines, stable array order `(normalized_name, primary_domain, cnx_article_url)`, one trailing newline. It includes the run id, `code_revision`, alias table version, roster sha256, `sample_source`, sample window, every fetch (URL, attempt, timestamp, status, content hash, robots decision, outcome), every lead with its reason, `article_title`, `comparison_mentions`, `homepage_url`, and the qualified queue with its sightings. CNX URLs appear only as article provenance (`cnx_article_url` and sightings), never as `primary_url`, `homepage_url`, or `primary_domain`.

Fixture runs pass `--now` and `--code-revision`. Two fixture runs with the same arguments produce byte-identical `report.json`. Live timestamps are recorded as observed; live determinism is stable ordering and stable keys, not frozen clock values.

### 3.3 Duplicate records on replay

`replay` does not read the live feed and does not fetch CNX article URLs again. It freezes the sample from a completed source run in the same state directory: `--from-run SOURCE_ID`, or, when that flag is omitted, the latest completed run other than the new `--run-id`. The frozen sample is that run's `article_urls_json` (the exact URL list, same order) and the stored response bodies and `content_sha256` values for the feed or listing fetch and for each of those article URLs.

Bodies live as files under `state_dir / "bodies" / "<content_sha256>.bin"`, written with `pathlib` when the source run fetched them. Replay reads those files. It does not GET `cnx-software.com`. A fixture or live feed that would now return different articles is ignored.

A live replay (`--live`) may GET non-CNX OEM URLs that the source run already fetched (homepage and board surface). Those responses are new `fetches` rows for the new `run_id` only. They do not change classification. Fixture replay does not open sockets at all; it reuses stored bodies for OEM pages as well.

Replay inserts nothing into `leads` or `qualified_candidates` and updates neither table. Existing lead rows and candidate rows stay byte-identical, including `reason_code`, `qualified`, `primary_url`, `homepage_url`, and `cnx_article_url`.

"No duplicate records" for the acceptance re-run means all of the following, and nothing stricter:

- Zero new rows in `qualified_candidates` (`new_qualified: 0`) and zero new rows in `leads`.
- Zero duplicate `candidate_key` values. The column is the primary key, and the replay must not replace or clone an existing key.
- The replay run's `article_urls_json` equals the source run's list. Its CNX `content_sha256` values equal the stored hashes. Those CNX rows, if copied into `fetches` for the new `run_id`, are marked outcome `reused` and are not network attempts.
- Per-run OEM `fetches` rows for the new `run_id` are allowed on a live replay. `run_id` is `NOT NULL`. Uniqueness is `(run_id, url, attempt)`.
- Per-run `article_sightings` and `lead_sightings` rows for the new `run_id` are allowed and must not alter lead or candidate rows. Both primary keys start with `run_id`. The same `(candidate_key, cnx_article_url)` may appear again under the new run id. It must not appear twice under one run id.
- A row with a null `run_id` is a schema error, not a replay result.

### 3.4 Code revision

`code_revision` is the full git SHA of the running code: 40 lowercase hexadecimal characters matching `^[0-9a-f]{40}$`. `UNKNOWN`, an empty string, a short SHA, and any uppercase or non-hex value are invalid. A run that does not have a valid SHA writes no qualified row and is not acceptance evidence.

Resolution order:

1. `--code-revision` if passed, else `$CNX_SEEDER_CODE_REVISION`.
2. Reject unless the value matches `^[0-9a-f]{40}$`.
3. When `.git` can be resolved, also read the checked-out SHA without a subprocess and reject the run if it differs. Resolution uses `pathlib` only: if `repo_root / ".git"` is a directory, read `HEAD`; if `HEAD` is `ref: <name>`, read that file under `.git` after rejecting absolute paths and `..` parts; if the ref file is missing, scan `.git / "packed-refs"` for that name. If `.git` is a file whose first line is `gitdir: <path>`, resolve `<path>` with `pathlib` and repeat. Do not execute the path.
4. `--live` always performs step 3 when `.git` resolves. A mismatch exits 2 before any socket and before any qualified insert.
5. Fixture mode records the supplied 40-hex value and does not require it to equal the developer checkout. Fixture mode still rejects a missing or invalid value, before any socket.

Acceptance and the acceptance replay are `--live` runs. Both `runs.code_revision` values must equal the candidate SHA that review names. Gates `reviewed_sha_equals_candidate_sha` and `real_cnx_run_with_fetch_provenance` fail if either run recorded any other string. The revision gate runs before network I/O, so a bad SHA cannot become a fetch.

## 4. Dedup against the roster

Placeholders and Jetson have `base_urls: []` in `config/sources.yaml`. The seeder therefore owns a versioned alias and domain table, `known-vendors-1`, shipped in BUILD at `src/cnx_seeder/data/known_vendors_v1.yaml`. That file is seeder data. It is not written into `config/sources.yaml` or `src/board_clank/sources.yaml`.

On every run the seeder:

1. Reads the roster YAML read-only and records its sha256.
2. Checks `meta.promotion_freeze` is true and that the vendor set is exactly the sixteen vendors in section 1, with Jetson `out_of_scope: true` and the nine placeholders `placeholder: true` and `base_urls: []`. A mismatch is a hard failure (`roster_mismatch`) and writes no candidates.
3. Checks every roster vendor has exactly one alias-table row. A missing row is a hard failure (`alias_table_incomplete`).
4. Checks every active source `base_urls` host, after `urllib.parse` and stripping one leading `www.`, appears in that vendor's alias-table domains. A missing host is `alias_table_incomplete`. Test 28 fails on this drift. Placeholder rows have no `base_urls` hosts; their domains exist only in the seeder table.

### 4.1 Normalization and matching mode

Normalization, applied to the extracted subject vendor and to every alias and SoC name:

1. Unicode NFKC, then casefold.
2. Replace `&` with ` and `.
3. Drop a trailing legal-form token: `inc`, `llc`, `ltd`, `co`, `corp`, `gmbh`, `limited`, `corporation`.
4. Replace hyphens and other punctuation with spaces. Do not delete characters in a way that glues tokens together.
5. Collapse whitespace and split on spaces. The result is a token tuple.

Alias names and SoC names match the subject vendor by whole-token equality only. The alias token tuple must equal the subject token tuple. Comparison is case-folded because step 1 casefolds. There is no character-substring test and no "alias occurs inside the article" scan. `pi` does not match `raspberrypi`. `rpi` does not match `raspberrypi`. `firefly` does not match `fireflies`. `renegade` does not match `renegade elite`. A longer alias matches only when extraction produced exactly those tokens.

SoC names use the same whole-token equality against the extracted subject vendor. They are not searched as substrings of the title or body. A SoC token that appears only inside a comparison or component span (section 6.1) is not the subject and does not classify the lead.

Domain match is separate from name match and is also not a character substring. `registrable_domain(host)`:

1. Lowercase, strip one leading `www.`, strip a trailing dot, drop the port. The input is a parsed hostname, not a raw URL.
2. If the last two labels are one of `co.uk`, `org.uk`, `ac.uk`, `com.cn`, `com.au`, `co.jp` and there are at least three labels, the registrable domain is the last three labels.
3. Otherwise, if there are at least two labels, it is the last two labels.

A host matches an alias domain or a SoC domain when `registrable_domain` of the host equals that domain. `wiki.radxa.com` equals `radxa.com`. `developer.nvidia.com` equals `nvidia.com`. `banana-pi.org` does not equal `pi.org`. `notcnx-software.com` does not equal `cnx-software.com`.

Decision order, first match wins. A match never enters `qualified_candidates`. The name being matched is the extracted subject vendor, not the article title and not a comparison mention.

| Order | Match | classification | reason_code |
| --- | --- | --- | --- |
| 1 | Subject vendor or its registrable domain hits Jetson / NVIDIA | `out_of_scope` | `out_of_scope_jetson` |
| 2 | Subject vendor or its registrable domain hits an active-source alias | `known_active` | `known_active_source` |
| 3 | Subject vendor or its registrable domain hits a placeholder alias | `known_placeholder` | `known_placeholder` |
| 4 | Else continue to classification in section 5 | | |

Product-line names in the table (`nanopi`, `beaglebone`, `le potato`, and the rest) are aliases of the already tracked vendor, not new OEMs. They match only when the extracted subject is exactly that alias. A title whose subject is a new maker, and which merely compares itself with a tracked vendor, does not dedup (section 6.1).

### 4.2 Alias table `known-vendors-1`

Reachability notes are HEAD or GET results from the SPEC environment on 2026-09-29 with user agent `CNXOemSeederSpecContext/0.1`. They are not ownership proof and they are not a crawl. Dedup uses the names and domains either way. A 403 or TLS failure is recorded here so BUILD does not bypass the site.

| vendor | role | match names | domains | SPEC reachability note |
| --- | --- | --- | --- | --- |
| `raspberry-pi` | active | raspberry pi, raspberrypi, rpi | `raspberrypi.com`, `raspberrypi.org` | `https://www.raspberrypi.com/` HTTP 403. `raspberrypi.com` is the active `base_urls` host. `raspberrypi.org` is an additional alias domain. |
| `orange-pi` | active | orange pi, orangepi, xunlong | `orangepi.org`, `orangepi.cn` | `http://www.orangepi.org/` HTTP 200 (registry is HTTP). `https://www.orangepi.org/` TLS EOF. `orangepi.cn` NXDOMAIN from the SPEC environment. Registry notes name `orangepi.cn` as a mirror that is not ingested. |
| `radxa` | active | radxa | `radxa.com` | `https://radxa.com/` HTTP 403. `docs.radxa.com` and `wiki.radxa.com` share registrable domain `radxa.com`. |
| `banana-pi` | active | banana pi, bananapi | `banana-pi.org` | `https://banana-pi.org/` HTTP 200 |
| `hardkernel-odroid` | active | hardkernel, odroid | `hardkernel.com`, `odroid.com` | `https://www.hardkernel.com/` HTTP 200. `https://odroid.com/` HTTP 403. `https://www.odroid.com/` NXDOMAIN. `wiki.odroid.com` shares registrable domain `odroid.com`. |
| `pine64` | active | pine64, pine 64 | `pine64.org`, `pine64.com` | `https://pine64.org/` HTTP 200. `pine64.com` is the commerce host named in the registry notes; same vendor for dedup. |
| `friendlyelec` | placeholder | friendlyelec, friendly elec, friendlyarm, friendly arm, nanopi, nanopc | `friendlyelec.com`, `friendlyarm.com` | `https://www.friendlyelec.com/` HTTP 200. `wiki.friendlyelec.com` shares registrable domain `friendlyelec.com`. `https://www.friendlyarm.com/` TLS certificate expired. |
| `milk-v` | placeholder | milk-v, milkv, milk v | `milkv.io` | `https://milkv.io/` HTTP 200 |
| `beagleboard` | placeholder | beagleboard, beagle board, beaglebone, beagleplay | `beagleboard.org` | `https://www.beagleboard.org/` HTTP 200 |
| `libre-computer` | placeholder | libre computer, librecomputer, le potato, renegade elite, tritium | `libre.computer` | `https://libre.computer/` HTTP 200. Bare token `renegade` is not an alias; `renegade elite` is. |
| `khadas` | placeholder | khadas, khadas vim, khadas edge | `khadas.com` | `https://www.khadas.com/` HTTP 200. Bare tokens `vim` and `edge` are not aliases. |
| `up-board` | placeholder | up board, up-board, up squared, up xtreme, aaeon | `up-board.org`, `up-shop.org`, `aaeon.com` | `https://up-board.org/` and `https://up-shop.org/` HTTP 200. `https://www.aaeon.com/` HTTP 403. AAEON is the manufacturer behind the tracked UP placeholder, so an AAEON lead is not a new OEM. |
| `seeed-studio` | placeholder | seeed, seeed studio, seeedstudio | `seeedstudio.com`, `seeed.cc` | `https://www.seeedstudio.com/` HTTP 200. `https://seeed.cc/` redirects to `https://www.seeed.cc/` HTTP 200. |
| `firefly` | placeholder | firefly, t-firefly, tfirefly | `t-firefly.com`, `firefly.store` | `https://www.t-firefly.com/` HTTP 200. `https://en.t-firefly.com/` redirects there. `https://www.firefly.store/` HTTP 200. |
| `lattepanda` | placeholder | lattepanda, latte panda, dfrobot, df robot | `lattepanda.com`, `dfrobot.com` | Both HTTPS hosts HTTP 200. DFRobot is the company behind the tracked LattePanda placeholder, so a DFRobot lead is not a new OEM. |
| `nvidia-jetson` | out of scope | nvidia, jetson, nvidia jetson, jetson orin, jetson nano, jetson xavier, jetson agx, jetson thor | `nvidia.com` | `https://www.nvidia.com/` HTTP 200. `https://developer.nvidia.com/` HTTP 200. `https://developer.nvidia.com/embedded/jetson` HTTP 404; dedup does not depend on that path. |

Bare `firefly` matches the placeholder when the extracted subject is exactly that token. `fireflies` does not match. Over-dedup of the English word `firefly` as a whole token is the intended failure direction. Substring matching is not.

## 5. Classification

After dedup, every remaining lead gets one label. Only `board_maker` can be qualified, and only when the positive rule in section 6.2 passes. A host that is absent from the denylist is not a board maker by default. If the positive rule is not met, the lead is `unresolved` (or a more specific denial below) and stays out of `qualified_candidates`.

| classification | meaning | qualified |
| --- | --- | --- |
| `board_maker` | The subject vendor's own domain shows company/about identity and hosts product pages, datasheets, or specs for boards it designs, and is not a storefront-only cart | only if section 6.2 passes |
| `soc_vendor` | The subject vendor is a silicon vendor | no |
| `distributor` | Multi-brand catalogue, or a denylisted distributor host | no |
| `reseller` | Storefront for brands it does not control, including an unlisted host | no |
| `single_product_name` | A model name with no company token | no |
| `out_of_scope` | NVIDIA / Jetson is the subject vendor | no |
| `media` | News, social, wiki-host, or the CNX site itself | no |
| `unresolved` | The positive board-maker rule was not met and no denial above applied | no |

SoC names, matched by section 4.1 whole-token equality on the subject vendor, or by registrable-domain equality: `rockchip` (`rock-chips.com`), `allwinner` (`allwinnertech.com`), `amlogic` (`amlogic.com`), `broadcom`, `mediatek` (`mediatek.com`), `qualcomm`, `intel` (`intel.com`), `amd` (`amd.com`). Label `soc_vendor`, reason `soc_vendor`. NVIDIA is not in this list; it is already out of scope in section 4 when it is the subject. A component mention such as `Allwinner H618` does not make the lead a SoC vendor (test 27).

Host denylist, matched by registrable-domain equality, reason as shown:

| Hosts | classification | reason_code |
| --- | --- | --- |
| `amazon.com`, `amazon.co.uk`, `aliexpress.com`, `alibaba.com`, `ebay.com`, `banggood.com`, `walmart.com` | `reseller` | `reseller` |
| `digikey.com`, `mouser.com`, `arrow.com`, `lcsc.com`, `avnet.com` | `distributor` | `distributor` |
| `cnx-software.com`, `wikipedia.org`, `medium.com`, `youtube.com`, `reddit.com`, `twitter.com`, `x.com`, `facebook.com`, `linkedin.com` | `media` | `media_or_marketplace` |
| `github.io`, `gitlab.io`, `wordpress.com`, `blogspot.com`, `wixsite.com`, `myshopify.com` | `unresolved` | `platform_host` |

The denylist is not sufficient for qualification. Section 6.2 is the positive `board_maker` rule. An unlisted storefront still fails that rule (test 29).

A lead whose extracted subject is empty, or is only a product token (a token containing a digit, or a lone `pro` / `plus` / `max` / `ultra` / `zero` / `mini` / `lite`), is `single_product_name` / `single_product_name`, not a new OEM.

Seeed Studio and DFRobot are already placeholders, so they dedup before this section when they are the subject vendor. If an article is about Seeed selling some other maker's board, the subject is that other maker only when section 6.1 selects it. Seeed's domain is never a qualified primary domain because dedup removes it when it is the subject.

## 6. First-party verification

A qualified candidate needs a manufacturer-controlled primary domain and a first-party board/product surface on that same registrable domain, plus the company/about evidence in section 6.2. Anything unfinished stays in `leads` with `qualified = 0` and one reason from section 6.5. It is not written to `qualified_candidates`.

### 6.1 Subject vendor extraction

The parser never evaluates page text, never sends it to a model, and never treats it as configuration. The article title is stored in `article_title` and is not copied into `normalized_name`.

Vendor extraction is a heuristic. A tie, an ambiguous brand, a masked span that leaves no subject, or any case these rules do not cleanly decide fails toward rejection. The lead stays out of `qualified_candidates` with `vendor_name_unresolved`, `ambiguous_primary`, `primary_domain_unresolved`, or `board_maker_unresolved`. The heuristic does not promote a guess into the qualified queue.

Preparation:

1. Decode as UTF-8 with replacement. If the bytes are empty or the content type is not HTML (and not the feed XML of section 7), reason `malformed_page`.
2. Drop `script`, `style`, `noscript`, and comments. Do not execute scripts.
3. If the remaining visible text casefolds onto any of these phrases, stop the article and do not follow its links: `ignore previous instructions`, `ignore all previous`, `system prompt`, `you are chatgpt`, `disregard the above`, `admit this source`, `promotion_freeze`, `enabled: true`. Reason `instruction_bearing_rejected`.
4. Tokenize the title and the first 200 words of visible body with the section 4.1 normalization (punctuation, including hyphens, becomes a token break).

Comparison and component spans are removed before the subject is chosen. A span is not the subject vendor. Record each removed name in `comparison_mentions_json`. Whole-token patterns, after casefold:

| Pattern | Example | What is masked |
| --- | --- | --- |
| `<name>` immediately followed by the token `alternative` | `Raspberry Pi alternative` | `raspberry pi` |
| `alternative to <name>`, `compared to <name>`, `comparison with <name>`, `vs <name>`, `versus <name>`, `similar to <name>`, `like <name>` | `alternative to Raspberry Pi` | the following 1–4 tokens of `<name>` |
| `<name>` immediately followed by the token `compatible` | `Jetson-compatible` (hyphen already split) | `jetson` |
| `powered by <name>`, `based on <name>`, `uses <name>` | `uses Allwinner H618` | `<name>` plus a following model token if that token contains a digit |

`<name>` is one to four tokens that are not themselves cue words. Masking applies in the title and in the body. The masked tokens are ignored by alias, SoC, and subject extraction. They do not set `normalized_name` and they do not set the primary domain, even when the masked name is a link anchor.

Subject vendor, first success wins, using only unmasked text:

1. **Company-name pattern.** A sequence of 1–4 tokens in the title or the first 200 words, immediately followed by a legal-form token (`inc`, `ltd`, `llc`, `co`, `corp`, `gmbh`, `limited`, `corporation`). Example: `Acme Boards Ltd` → discovered name `Acme Boards`, normalized `acme boards`.
2. **Leading brand token(s) before a product token.** Walk the title from the left. Skip product-class tokens `sbc`, `board`, `boards`, `carrier`, `module`, `som`, `devkit`, `kit`. Collect up to three brand tokens. Stop before the first product token. A product token contains a digit, or is `pro`, `plus`, `max`, `ultra`, `zero`, `mini`, or `lite` after at least one brand token. Example: title `Acme Board X1 brings a new SBC` → brand token `Acme`, product token `X1`, normalized name `acme`. The stored title remains the full string.
3. **Link to a vendor domain.** An absolute `http` or `https` link whose parsed host is not CNX (section 6.4), not denylisted, and not a platform host, and whose anchor is not inside a masked span. Take the anchor's leading brand tokens by rule 2. The link's registrable domain is the proposed primary domain. Example: anchor `Acme` to `https://acme.example/products/x1`.

If rules 1–3 do not produce a vendor name, reason `vendor_name_unresolved`. Do not fall back to the whole title.

Proposed primary domain: the registrable domain from rule 3 if that rule supplied the name; otherwise the most frequent remaining absolute-link registrable domain that is not CNX, not denylisted, and not a platform host. A tie or an empty set is `ambiguous_primary` or `primary_domain_unresolved`. Redirects update the domain to the final host's registrable domain. That final value is the domain inside `candidate_key`.

### 6.2 Positive board-maker rule

Fetch budget for the lead is `max_oem_fetches_per_lead` (3): the homepage, then one same-domain about/company URL if present, then one same-domain product, datasheet, or spec URL. Path fragments that identify those pages: `about`, `company`, `about-us`, `product`, `products`, `board`, `boards`, `sbc`, `devices`, `datasheet`, `specs`, `specifications`.

All three of the following are required. The denylist does not replace them.

1. **Company/about identity.** A fetched HTTPS 200 HTML page on the resolved registrable domain (homepage or about/company path) contains the normalized vendor name as a whole-token tuple and at least one identity phrase: `we design`, `designed by`, `we manufacture`, `manufacturer`, `our boards`, `about us`. The final URL of that page is stored as `homepage_url`. This is the verified homepage/primary evidence URL.
2. **First-party board surface.** A fetched HTTPS 200 HTML page on that same registrable domain has a path containing `product`, `products`, `board`, `boards`, `sbc`, `devices`, `datasheet`, `specs`, or `specifications`, and its visible text contains the vendor name as whole tokens plus one scope term: `sbc`, `single board computer`, `single-board computer`, `development board`, `dev board`, `system on module`, `compute module`, `datasheet`, `specifications`. That final URL is `primary_url` and `board_surface_url`. It must differ from `cnx_article_url`. It may equal `homepage_url` only when the same page meets both item 1 and item 2.
3. **Not a storefront-only cart for third-party brands.** If the fetched pages contain two or more brand tokens that are not the subject vendor, classification is `reseller`, reason `reseller`. If the pages contain a cart phrase (`add to cart`, `buy now`, `add to basket`) and do not contain an identity phrase from item 1, classification is `reseller`, reason `storefront_only`. Either result is unqualified, including when the host is not on the denylist.

Scheme for a new candidate is `https` and the final response is HTTP 200. The existing Orange Pi HTTP registry entry is irrelevant here because that vendor dedups when it is the subject.

If identity is missing, or the surface is missing, and no reseller/storefront rule fired, classification is `unresolved`, reason `board_maker_unresolved`. If the brand string is absent from a page that was otherwise a candidate surface, reason `brand_domain_mismatch`. A page that fails these checks stays unresolved even if a person might recognize it. The acceptance run does not require a non-zero qualified count.

### 6.3 Sample URLs

From the RSS feed (section 7), keep item links whose parsed host is CNX and whose path matches `^/20[0-9]{2}/[0-9]{2}/[0-9]{2}/[^/]+/?$`, in document order, truncated to `max_articles`. If the feed is not used, the HTML listing uses the same path rule and the same cap, and at most `max_listing_pages` listing pages. Any other host on the listing or in the feed is ignored. A CNX host is never copied into `primary_domain`, `primary_url`, or `homepage_url`.

### 6.4 CNX host exclusion

`is_cnx_host(host)` is true when the parsed hostname, lowercased, with one leading `www.` and a trailing dot removed, equals `cnx-software.com` or ends with `.cnx-software.com`. Subdomains such as `shop.cnx-software.com` and `www.cnx-software.com` are CNX. `notcnx-software.com` and `cnx-software.com.example` are not. The test is on the parsed host, not a substring of the URL.

The function runs in the extractor and again in the insert function. A true result drops the URL as a primary, homepage, or board-surface candidate. The article URL may use a CNX host; that is the only column where a CNX host is stored. The `CHECK` constraints and the two triggers in section 3.1 reject a queue row that still carries a CNX primary, homepage, or domain. Test 30 covers the parser and a direct `INSERT`.

### 6.5 Closed reason codes

`qualified`, `known_active_source`, `known_placeholder`, `out_of_scope_jetson`, `soc_vendor`, `distributor`, `reseller`, `storefront_only`, `single_product_name`, `media_or_marketplace`, `platform_host`, `robots_disallow`, `http_blocked`, `fetch_failed`, `primary_domain_unresolved`, `ambiguous_primary`, `vendor_name_unresolved`, `board_surface_unresolved`, `board_maker_unresolved`, `brand_domain_mismatch`, `instruction_bearing_rejected`, `malformed_page`, `roster_mismatch`, `alias_table_incomplete`.

Every non-qualified lead stores exactly one of these, other than `qualified`. `board_surface_unresolved` is unused when `board_maker_unresolved` already covers a missing surface; BUILD uses `board_maker_unresolved` for a failed positive rule and `board_surface_unresolved` only when identity passed and the surface fetch did not.

## 7. Run bounds

Constants live in one module, `cnx_seeder/bounds.py`, and are the values the tests assert.

| Bound | Value |
| --- | --- |
| Feed URL (preferred sample) | `https://www.cnx-software.com/news/sbc/feed/` |
| HTML listing (fallback only) | `https://www.cnx-software.com/news/sbc/` |
| `max_listing_pages` | 2, and only for the HTML fallback |
| `max_articles` | 20 |
| `max_oem_fetches_per_lead` | 3 |
| Per-host interval | 2.0 seconds between the start of requests to the same host |
| Concurrency | 1 |
| Timeout | 15 seconds |
| Retries | 1 extra attempt (`attempt` 2), same URL, same user agent, only after HTTP 429, 500, 502, 503, 504, or a timeout |
| No retry | HTTP 401, 403, 404, robots disallow, TLS error, DNS error. These stay `attempt` 1. |
| Max body | 1_500_000 bytes. Stop reading, set outcome `fetch_failed`, do not parse the body, do not qualify from it. |
| User agent | `CNXOemSeeder/0.1 (COPS-000080; observation-only; +https://github.com/anil-ganti-nbc/board-clank)` |
| Robots token | `CNXOemSeeder` |

Sample order:

1. Honor robots for the feed host. If robots disallow the feed path, do not fetch it.
2. If robots allow it, fetch the feed once. On HTTP 200, parse with `xml.etree.ElementTree` after rejecting a body that contains `<!doctype` or `<!entity` (casefold). Do not resolve external entities. Item descriptions are untrusted and go through the instruction lexicon; a matching item is skipped.
3. Fallback to the HTML listing only when the feed fetch is HTTP 404, the feed body is malformed XML, or the feed yields zero article links. An access-control response on the feed does not fall back. Access-control statuses are 401, 403, 407, and 429. Record the feed fetch as `http_blocked`, set the run status to `blocked`, and stop. Do not request the HTML listing, a later listing page, or any article. 401, 403, and 407 are not retried. 429 uses the single retry in the bounds table and, if it is still 429, stops the same way. Any other feed failure (5xx after the retry budget, timeout, TLS, DNS) is recorded and also does not fall back. Do not concatenate feed items with listing items. `max_articles` applies to whichever source was actually used. `sample_source` records `feed` or `html`. A stopped access-control run records `sample_source=feed` and an empty article list.
4. HTML pagination uses only a same-host link on an HTTP 200 listing page whose path matches `^/news/sbc/page/[0-9]+/?$`, and only while both caps allow it. If the seed listing is not HTTP 200, stop. Do not guess `/page/2/` to get around that result. The feed is a single URL; do not invent further feed pages.

Robots:

- Fetch `https://<host>/robots.txt` once per host per run and parse it with `urllib.robotparser`.
- Honor `Disallow` for token `CNXOemSeeder` and for `*`.
- If `robots.txt` is not HTTP 200, fail closed for that host (`robots_decision=robots_unavailable`). Record the robots fetch. Do not fetch any other URL on that host, including the page that was about to be requested.
- A disallow records `outcome=blocked`, reason `robots_disallow`, and does not fetch the URL.
- Do not impersonate `GrokBot`, `ChatGPT-User`, `CCBot`, `PerplexityBot`, `Claude-Web`, `OAI-SearchBot`, or a browser.
- Do not use the sitemap as a crawl frontier.

The robots file read during SPEC allows `User-agent: *` except `/wp-admin/`, and sets `Crawl-delay: 60` only for Awario bots. Several named training crawlers are disallowed entirely. `CNXOemSeeder` is not one of them. The coordinator reports that this file allows `/news/sbc/` and `/news/sbc/feed/`. Each live run re-reads robots.txt and obeys the live file rather than this snapshot.

When access is blocked (401, 403, 404, robots disallow, TLS or DNS failure, or the retry budget exhausted): write the `fetches` row for each attempt that was actually made, keep the lead unresolved with `http_blocked` or `robots_disallow` or `fetch_failed`, and continue only with hosts that are still allowed. A blocked or access-control response on the feed is the exception in sample-order step 3: stop the run and do not open the HTML listing. Do not change the user agent, do not switch proxy, do not ignore robots, do not open a mirror, and do not read a cached copy from a third party.

SPEC context, not an acceptance run: the Cursor VM received HTTP 403 for the HTML listing with user agent `CNXOemSeederSpecContext/0.1`. The acceptance `--live` run is performed on the coordinator's Windows host, which receives HTTP 200 for the listing and the feed. The run records whatever status that host actually gets. A blocked response is recorded. It is not retried with another agent string.

Fixture mode performs no socket calls (test 36). The rate-limit test uses an injected clock and asserts the scheduled gap is at least 2.0 seconds. It does not sleep on the wall clock.

## 8. Acceptance tests

BUILD adds focused tests under `tests/test_cnx_seeder.py` and `tests/test_cnx_seeder_isolation.py`. They use local HTML and RSS fixtures and a fixture clock. They do not call the network, except where a test asserts that a call did not happen. The applicable full suite stays hermetic because of the black-hole proxy.

Each case below is one test (or one parametrized case). Expected queue effects are on the seeder SQLite file only. Every fixture run passes `--code-revision` set to a 40-hex string unless the test is specifically about an invalid revision.

1. **Active names.** For each of `raspberry pi`, `orange pi`, `radxa`, `banana pi`, `hardkernel`, `odroid`, `pine64`, a fixture whose extracted subject vendor is that name is `known_active` / `known_active_source`, `qualified = 0`, and `qualified_candidates` is empty. The match is whole-token equality, not a substring.
2. **Active domains.** The same result for links to `raspberrypi.com`, `raspberrypi.org`, `orangepi.org`, `orangepi.cn`, `radxa.com`, `wiki.radxa.com`, `banana-pi.org`, `hardkernel.com`, `odroid.com`, `wiki.odroid.com`, `pine64.org`, and `pine64.com`. `raspberrypi.org` is required here even though it is not an active `base_urls` host.
3. **Placeholder names.** One case per placeholder vendor name in section 4.2, including `friendlyelec`, `milk-v`, `beagleboard`, `libre computer`, `khadas`, `up board`, `seeed studio`, `firefly`, `lattepanda`. Each is `known_placeholder`, not qualified. `fireflies` does not match `firefly`.
4. **Placeholder domains despite empty `base_urls`.** One case per domain in section 4.2's placeholder rows, including `friendlyelec.com`, `milkv.io`, `beagleboard.org`, `libre.computer`, `khadas.com`, `up-board.org`, `aaeon.com`, `seeedstudio.com`, `seeed.cc`, `t-firefly.com`, `firefly.store`, `lattepanda.com`, `dfrobot.com`. The test loads `base_urls` from the read-only roster and asserts they are `[]` for those nine vendors, then asserts dedup still happens via the seeder table.
5. **Aliases.** `nanopi` and `friendlyarm` map to `friendlyelec`. `beaglebone` maps to `beagleboard`. `le potato` maps to `libre-computer`. `aaeon` maps to `up-board`. `dfrobot` maps to `lattepanda`. `milkv` maps to `milk-v`. Bare `vim` and bare `edge` do not map to `khadas`. Bare `renegade` does not map to `libre-computer`. None of the mapped names are qualified.
6. **Jetson.** Subject names `jetson`, `nvidia jetson`, `jetson orin` and domain `developer.nvidia.com` are `out_of_scope` / `out_of_scope_jetson`, not qualified, and not classified as a new board maker. A title where Jetson is only the masked `Jetson-compatible` span is not this test (test 27).
7. **False OEM, silicon.** The subject vendor `Rockchip`, and a subject whose registrable domain is `allwinnertech.com`, are `soc_vendor`. They are not qualified. `Allwinner` inside `uses Allwinner H618` is not this test (test 27).
8. **False OEM, reseller and distributor.** A subject domain `amazon.com` is `reseller`. `digikey.com` is `distributor`. Neither is qualified.
9. **False OEM, product name.** Title `Orange Pi 5 Plus` extracts subject `orange pi` and dedups to `orange-pi`. Title `X9 Pro` extracts no brand token and is `single_product_name`. Neither is qualified. The stored `article_title` is the full title in both cases.
10. **False OEM, media.** A lead whose only external site is `cnx-software.com` or `shop.cnx-software.com` is not qualified. Neither host is stored as `primary_domain`.
11. **First-party pass.** Fixture article title is `Acme Board X1 brings a new SBC`. That full string is `article_title` and is not `normalized_name`. Extraction yields subject `acme` (leading brand token before product token `X1`; `Board` is a skipped product-class token). The article links to `https://acme.example/` and `https://acme.example/products/sbc`. Homepage HTML contains the whole token `acme` and the phrase `we design`. Product HTML contains `acme`, `single board computer`, and a product path. The single qualified row has `classification = board_maker`, `normalized_name = acme`, `homepage_url = https://acme.example/`, `primary_url = https://acme.example/products/sbc`, `primary_domain = acme.example`, and `cnx_article_url` equal to the fixture article URL. `primary_url` and `homepage_url` both differ from `cnx_article_url`. `candidate_key` equals hex sha256 of `known-vendors-1\nacme\nacme.example`. `content_sha256`, `fetched_at`, HTTP status 200, `run_id`, and `code_revision` are present. `code_revision` is the 40-hex flag value. One `article_sightings` row records that article.
12. **Positive rule incomplete.** Homepage contains the vendor name and `we design`, and the other fetches have no scope term and no datasheet or spec path. Reason `board_maker_unresolved`. No qualified row. `homepage_url` may be recorded on the lead; `qualified_candidates` stays empty.
13. **Brand mismatch.** Product page is on `acme.example` but visible text never contains the extracted vendor as whole tokens. Reason `brand_domain_mismatch`. No qualified row.
14. **Unresolved reason is stored.** Every non-qualified fixture lead has a non-empty `reason_code` from section 6.5 and `qualified = 0`.
15. **Malformed page.** Empty body, non-HTML bytes, and truncated markup each yield `malformed_page`, exit code 0, and no qualified row.
16. **Instruction-bearing page.** Fixture HTML whose visible text says to ignore previous instructions and to set `enabled: true` in `sources.yaml` yields `instruction_bearing_rejected`. The test's sha256 of both `sources.yaml` copies is unchanged. No link in that document is fetched.
17. **Registry separation.** After a fixture run, sha256 of `config/sources.yaml` and of `src/board_clank/sources.yaml` is still `ba2a5bc4a25f4b7836b7ec99b9c7dfdee5593bd863a6cacb63f4a710339fd6ab` and the two files still compare equal. Meta `promotion_freeze` is true. All `enabled` flags are false. The six active keys, nine placeholders, and Jetson row are unchanged. The test reads the files; it does not trust a status flag inside the seeder.
18. **Event and outbox separation.** A temp operational DB is seeded with one `sources` row, one `events` row, one `notifications` row (`channel = outbox`), one `canonical_observations` row, and one `novelty_evidence` row. `BOARD_CLANK_DB` points at that file. The seeder is run with a different `--state-dir`. The test recomputes counts and ordered-row sha256 for every `EXPECTED_TABLES` name. The diff is empty. `queue.sqlite` has none of those table names.
19. **Import and path guard.** The AST checks and the refusal checks in section 2.4 pass, including the ban on `subprocess` and POSIX-only modules. Refusing the operational path does not create `data/board_clank.db`.
20. **Deterministic output.** Two `run` invocations with the same `--fixture`, `--run-id`, `--now`, `--code-revision`, and `--state-dir` (the second is the no-op path) produce byte-identical `report.json`. A fresh state directory with the same arguments also produces that same byte string.
21. **Replay idempotency.** Run A inserts one qualified candidate from a fixture feed whose article URL list is U1. Before replay, replace that fixture feed with a different article URL U2. Replay uses a new `--run-id`, `--from-run` set to run A, and the same `--code-revision`. It does not request the feed URL, U1, or U2. The replay run's `article_urls_json` equals run A's list, and the CNX content hashes equal run A's stored hashes, read from `bodies/<sha256>.bin`. `new_qualified` is 0. `COUNT(*)` of `qualified_candidates` stays 1 and that `candidate_key` occurs once. A dump of `leads` and of `qualified_candidates` is byte-identical to the dump taken before replay. Run B may add OEM `fetches` only when `--live` is set, plus `lead_sightings` and `article_sightings` rows, and every one of those new rows has `run_id` equal to run B. Fixture replay adds no socket call. This is the rule in section 3.3.
22. **Alias table covers the live roster.** The test parses `config/sources.yaml` read-only, asserts one alias row per vendor, and fails if a roster vendor is missing. It also asserts the table's role for Jetson is out of scope.
23. **Caps.** A fixture feed of 50 item links keeps at most 20 articles and does not fetch the HTML listing. A fixture whose feed is HTTP 404 falls back to HTML. A fixture whose feed body is malformed XML falls back to HTML. A fixture whose feed is well-formed and has zero items falls back to HTML. That HTML fixture links `/news/sbc/page/2/` and `/news/sbc/page/3/` and fetches at most 2 listing pages and at most 20 articles. A fixture whose feed is HTTP 503 records the feed failure and does not request the HTML listing.
24. **Robots disallow and HTTP 403 / 500.** A fixture robots file that disallows `/secret` records `robots_disallow` and the HTTP client mock shows zero fetches of that URL. A fixture HTTP 403 records `http_blocked`, sends the constant user agent, uses `attempt` 1 only, and does not send a second request with a different user agent. A fixture HTTP 500 is stored as `attempt` 1 and `attempt` 2 under `UNIQUE (run_id, url, attempt)`, same user agent, and is not tried a third time.
25. **No operational DB creation.** With `BOARD_CLANK_DB` unset and `repo_root / "data" / "board_clank.db"` absent, a fixture run leaves that path absent.
26. **Multi-article same OEM.** Two fixtures, titles `Acme Board X1 brings a new SBC` and `Hands on with the Acme Board X2`, each link to `https://acme.example/` and `https://acme.example/products/sbc` with the test 11 page bodies. Both extract normalized name `acme` and registrable domain `acme.example`. The queue contains one `qualified_candidates` row, one `candidate_key`, and two `article_sightings` rows with the two CNX article URLs. The qualified row's `cnx_article_url` remains the first article. The second article does not add a qualified row.
27. **Comparison mentions are not the subject.** Three fixtures, each with Acme's first-party pages from test 11 so the subject can qualify: (1) title `Acme Board X1 is a Raspberry Pi alternative` extracts `acme`, stores `raspberry pi` in `comparison_mentions_json`, and is not `known_active`; (2) title `Acme X1 SBC uses Allwinner H618` extracts `acme`, stores the Allwinner mention, and is not `soc_vendor`; (3) title `Jetson-compatible Acme Carrier C2` extracts `acme`, stores `jetson`, and is not `out_of_scope`. Each qualified `candidate_key` uses `acme` plus `acme.example`, not the mentioned name. A body substring `raspberry` inside `raspberrypi` is not a match path in these fixtures; the alias compare is whole-token equality on the subject only.
28. **Active `base_urls` hosts are in the alias table.** The test parses `config/sources.yaml` read-only, takes every source with `placeholder` false and `out_of_scope` false, parses each `base_urls` entry, strips one leading `www.`, and asserts that host is a member of that vendor's `domains` in `known-vendors-1`. The current six hosts are `raspberrypi.com`, `orangepi.org`, `radxa.com`, `banana-pi.org`, `hardkernel.com`, and `pine64.org`. If a later roster edit adds a host the alias table does not list, this test fails. It does not write the roster.
29. **Unlisted reseller storefront.** Fixture host `bargain-boards.example` is not on the denylist. The page contains `add to cart` and names both `Acme Board` and `OtherCo Board`, and it has none of the section 6.2 identity phrases. Classification is `reseller`, reason `reseller`. A second fixture with only `buy now`, a single third-party brand, and no identity phrase is `storefront_only`. Neither inserts a qualified row.
30. **CNX exclusion.** Fixtures whose only non-article links are `https://www.cnx-software.com/shop/` and `https://shop.cnx-software.com/board` produce no `primary_domain` and no qualified row. A direct `INSERT` into `qualified_candidates` with `primary_host = shop.cnx-software.com` or `homepage_host = cnx-software.com` raises from the trigger and leaves the row absent. `is_cnx_host("notcnx-software.com")` is false. A qualified row's `homepage_url` in the success fixture is the non-CNX homepage from test 11.
31. **Code revision.** A fixture run with `--code-revision` set to `0123456789abcdef0123456789abcdef01234567` stores that exact value on `runs.code_revision` and in `report.json`. The same invocation with the flag omitted, with `UNKNOWN`, with `0123456789abcdef`, or with an uppercase SHA exits 2, performs no socket call, and inserts no qualified row. `--live` with a 40-hex value that differs from the SHA read from `.git` exits 2 before any socket. The acceptance run and the acceptance replay are valid only when both stored revisions equal the candidate SHA (section 8.1, gates 10 and 14).
32. **robots.txt non-200 fails closed.** A fixture where `robots.txt` returns HTTP 503 or HTTP 404 records `robots_decision=robots_unavailable` and the client mock shows no later request to that host.
33. **Body size cap.** A fixture whose body is 1_500_001 bytes records `fetch_failed`, stores at most 1_500_000 bytes, does not parse the overflow as HTML, and inserts no qualified row from that response.
34. **No retry on TLS, DNS, 401, or 404.** Each case records only `attempt` 1. The mock shows one request. Contrast with test 24, where HTTP 500 records `attempt` 1 and `attempt` 2.
35. **Per-host minimum interval.** With an injected clock and two URLs on the same host, the second request's scheduled time is at least 2.0 seconds after the first. Two different hosts are not held to that gap. The test does not sleep on the wall clock.
36. **Fixture mode makes zero network calls.** The test wraps `socket.socket` and `socket.create_connection` to count calls, runs a fixture `run` and a fixture `replay`, and asserts the count stays 0.
37. **Copied path rules stay in sync.** Under a temp `BOARD_CLANK_DB`, under a temp `BOARD_CLANK_DATA_DIR` with `BOARD_CLANK_DB` unset, and with both unset, `cnx_seeder.paths.operational_db_path(repo_root)` and `board_clank.paths.default_db_path()` return the same path. The seeder module's AST does not import `board_clank`.
38. **Feed access-control does not fall back.** A fixture feed of HTTP 403 records `http_blocked`, writes an empty article list, and the client mock shows no request to `https://www.cnx-software.com/news/sbc/` or to any `/news/sbc/page/` URL. The same holds for a feed of HTTP 401 and for a feed that stays HTTP 429 after the one allowed retry. `qualified_candidates` stays empty.

Applicable full suite, after the focused tests, from the repo root:

```
NO_PROXY=127.0.0.1,localhost,::1 \
HTTP_PROXY=http://127.0.0.1:9 \
HTTPS_PROXY=http://127.0.0.1:9 \
ALL_PROXY=http://127.0.0.1:9 \
pytest -q
board-clank sources --assert-foundation
```

`pytest -q` already selects `tests/` via `pyproject.toml`. The transcript that counts as evidence is the exit code plus the pytest summary line, and the exit code of `board-clank sources --assert-foundation`. Focused-test success does not replace this command. On Windows the same commands apply with the venv's `python -m pytest` if `pytest` is not on `PATH`. The black-hole proxy variables are set in the process environment either way.

Before/after operational comparison for the acceptance run (in addition to tests 17 and 18):

1. Record sha256 of both `sources.yaml` copies and whether the operational DB path from section 2.5 exists.
2. If it exists, record `COUNT(*)` and an ordered-row sha256 for `sources`, `events`, `notifications`, `canonical_observations`, `novelty_evidence`, and the other `EXPECTED_TABLES` names. Use a read-only SQLite open.
3. Run the seeder against its own state directory.
4. Repeat the measurements. Publish the two snapshots. The diff must be empty, including "file absent" to "file absent". An in-process assertion is not a substitute for the snapshots.

### 8.1 PASS gate evidence

The seventeen frozen keys stay as written. This table says how each one is shown. It does not mark the mission PASS.

| # | Gate key | How it is evidenced |
| --- | --- | --- |
| 1 | `contract_frozen_before_build` | This spec embeds contract v1 unchanged and records sha256 `a7c2f1d10d0bf427642c437362446165bb519adf7c05a95f7a980d0558f53456`. The SPEC commits contain only this file and are ancestors of any later BUILD commit. BUILD does not edit the appendix. Hermes records the frozen version before implementation starts. |
| 2 | `clankops_mission_and_sessions` | Hermes records Mission COPS-000080, the SPEC session, and later BUILD/TEST/REVIEW sessions in ClankOps, each citing the git SHA it actually used. A sentence in this repo is not that record. |
| 3 | `cnx_only_in_discovery_provenance` | Tests 10, 16, 17, 18, 19, and 30. Qualified and rejected CNX URLs exist only as article provenance in `queue.sqlite` and `report.json`. `primary_url`, `homepage_url`, and `primary_domain` reject CNX hosts in code and in the insert triggers. Both registry files contain no `cnx-software.com` host after the run. `src/board_clank` does not import `cnx_seeder`. |
| 4 | `qualified_candidates_have_primary_domain_and_board_surface` | SQL checks plus tests 11, 12, 13, 26, and 29. Every qualified row has `primary_domain`, `primary_url`, and `homepage_url`. The acceptance report lists those fields and a reason code on every other lead. |
| 5 | `active_and_placeholder_dedup` | Tests 1 through 6, 22, and 28, covering all six active vendors, their `base_urls` hosts, `raspberrypi.org`, all nine placeholders, aliases, domains, and Jetson. Comparison mentions are test 27 and are not dedup hits. |
| 6 | `focused_tests` | `pytest -q tests/test_cnx_seeder.py tests/test_cnx_seeder_isolation.py` under the black-hole proxy exits 0. The transcript is the evidence. |
| 7 | `applicable_full_suite` | The two commands in section 8 exit 0 on the candidate SHA. CI does not run on a push of `factory/cops-000080-cnx-seeder`. A later pull-request check is extra. Neither check is deployment proof. |
| 8 | `independent_sol_review` | Sol, via Hermes (`hermes -z / chat --query-file`, `-m gpt-5.6-sol --provider openai-codex`), reads the frozen contract, the diff, the tests, and the run evidence. The builder does not self-certify. If Sol cannot be reached, the mission is `BLOCKED` or `HUMAN_REQUIRED` and names that missing route. |
| 9 | `open_review_findings` | Sol's finding list is empty on the reviewed SHA after any fixes and a rerun of the focused tests and the full suite. |
| 10 | `reviewed_sha_equals_candidate_sha` | The SHA Sol reviewed, the SHA proposed for acceptance, `runs.code_revision` on the acceptance `--live` run, and `runs.code_revision` on the acceptance replay are the same 40-hex string. Test 31 locks the mechanism. A row stored as `UNKNOWN` fails this gate. |
| 11 | `operational_source_registry_diff` | Before/after sha256 snapshots of both `sources.yaml` copies are equal to each other and equal to the pre-run digest. Roster shape from section 1 is unchanged. Test 17 is the automated form. |
| 12 | `operational_db_event_outbox_diff` | Before/after count and ordered-row hashes for the operational tables in section 8 are equal, or the operational file is absent both times and was not created. Test 18 is the automated form. |
| 13 | `replay_new_candidates` | Test 21 and the acceptance re-run. Replay reuses the source run's article URL list and stored CNX bodies and hashes. `new_qualified` is 0, `leads` and `qualified_candidates` are unchanged, and no `candidate_key` is duplicated. New OEM fetch and sighting rows are allowed only when their `run_id` is the replay run (section 3.3). |
| 14 | `real_cnx_run_with_fetch_provenance` | The Windows acceptance `--live` run and its replay each store `code_revision` equal to the candidate SHA (gate 10). `report.json` for the live run records `sample_source`, the sample window, timestamps, article URLs, per-URL status, attempt, content hashes, robots decisions, `homepage_url`, `primary_url`, qualified rows, sightings, and rejected rows with reasons. A blocked listing is recorded as blocked. It is not retried with another agent string. The Cursor VM 403 is not this run. |
| 15 | `observation_only_deployment` | See section 9. Verified only for an isolated seeder process with its own state directory, no change to the `board-clank` compose command, scheduler, or notification path. A host deploy that needs NAS or host authority stays `HUMAN_REQUIRED` until the operator runs the section 9 unit on `<BOARD_HOST>`. |
| 16 | `natural_cycles` | At least two natural cycles of the deployed observation-only seeder (`natural_cycles: at_least_2`). A local sample run is not a natural cycle. The section 9 timer is how those cycles are produced. This cell adds no pass rule beyond the contract key. |
| 17 | `rollback_drill` | The section 9 rollback commands were actually run: the timer is disabled, only the seeder state directory was moved to quarantine, and the operational snapshots are still empty. Deleting a temp directory on a developer machine is the procedure check, not the host drill. |

## 9. Observation-only deployment and rollback

The seeder is a separate process. It is not the `board-clank` container command, not a compose service on the `board-clank-data` volume, and not a hook in `board-clank collect`. `scheduler_authority` and `notification_authority` stay `NONE`. The process gets a state directory that fails the section 2.3 guard if it is pointed at Board's database or data directory. It has no Discord webhook and no outbox write.

Placeholders in the commands below are written in angle brackets. They are not real host names, SHAs, or accounts. Replace each one before execution and do not leave the bracket text in the command.

| Placeholder | Replace with |
| --- | --- |
| `<BOARD_HOST>` | The operator-owned host where the soak timer will run. This spec does not name that host. |
| `<REVIEWED_SHA>` | The 40-hex lowercase SHA Sol reviewed. A branch name is not a SHA. |
| `<SEEDER_USER>` | An unprivileged account on `<BOARD_HOST>` that does not own Board's data volume. |
| `<REPO>` | The checkout path on the machine that is about to run the command. |

### 9.1 Acceptance run on the coordinator Windows host

This is the real CNX run for gate 14. It is not a NAS soak and it does not close gates 15, 16, or 17. The coordinator host is the machine that receives HTTP 200 for the feed and the listing. Do not point this run at the Cursor VM that received HTTP 403.

```
Set-Location <REPO>
git fetch origin
git checkout --detach <REVIEWED_SHA>
if ((git rev-parse HEAD) -ne "<REVIEWED_SHA>") { throw "HEAD is not the reviewed SHA" }
py -3.12 -m venv .venv-cnx-seeder
.\.venv-cnx-seeder\Scripts\python.exe -m pip install -e .
$env:CNX_SEEDER_CODE_REVISION = "<REVIEWED_SHA>"
$env:CNX_SEEDER_STATE_DIR = "<REPO>\var\cnx-seeder"
New-Item -ItemType Directory -Force -Path $env:CNX_SEEDER_STATE_DIR | Out-Null
.\.venv-cnx-seeder\Scripts\python.exe -m cnx_seeder.cli run --live --state-dir $env:CNX_SEEDER_STATE_DIR --run-id accept-1 --code-revision <REVIEWED_SHA>
.\.venv-cnx-seeder\Scripts\python.exe -m cnx_seeder.cli replay --live --state-dir $env:CNX_SEEDER_STATE_DIR --run-id accept-1-replay --from-run accept-1 --code-revision <REVIEWED_SHA>
```

The state directory is `<REPO>\var\cnx-seeder`. It must not be `BOARD_CLANK_DB` and must not be a `board_clank.db` path. After both commands, `runs.code_revision` for `accept-1` and for `accept-1-replay` is `<REVIEWED_SHA>`, replay reports `new_qualified: 0`, and section 3.3 holds.

Rollback of this acceptance run only (no service was installed):

```
Rename-Item -Path "<REPO>\var\cnx-seeder" -NewName ("cnx-seeder-quarantine-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ"))
```

Do not delete a Board database in that step. If a task named `CNXOemSeeder` was created outside this handoff, remove it with `schtasks /Delete /F /TN "CNXOemSeeder"`. This acceptance handoff does not create that task.

### 9.2 Soak on `<BOARD_HOST>` (HUMAN_REQUIRED)

Installing the timer needs host authority and crosses the Board/NAS freeze. Until an operator runs this section on `<BOARD_HOST>`, gates 15, 16, and 17 stay `HUMAN_REQUIRED`. The smallest operator action is the install, the unit files, and two timer days below. Do not mount `board-clank-data`. Do not change `config/sources.yaml`, the packaged roster, the compose `command`, or any Board timer.

Install from the reviewed SHA:

```
sudo install -d -o <SEEDER_USER> -m 0750 /var/lib/cnx-oem-seeder
sudo -u <SEEDER_USER> git clone --no-checkout https://github.com/anil-ganti-nbc/board-clank.git /opt/cnx-oem-seeder/src
sudo -u <SEEDER_USER> git -C /opt/cnx-oem-seeder/src fetch origin
sudo -u <SEEDER_USER> git -C /opt/cnx-oem-seeder/src checkout --detach <REVIEWED_SHA>
test "$(sudo -u <SEEDER_USER> git -c safe.directory=/opt/cnx-oem-seeder/src -C /opt/cnx-oem-seeder/src rev-parse HEAD)" = "<REVIEWED_SHA>"
sudo -u <SEEDER_USER> python3 -m venv /opt/cnx-oem-seeder/venv
sudo -u <SEEDER_USER> /opt/cnx-oem-seeder/venv/bin/python -m pip install -e /opt/cnx-oem-seeder/src
```

State directory: `/var/lib/cnx-oem-seeder`. Code revision in the environment and on the command line: `<REVIEWED_SHA>`.

Write `/etc/systemd/system/cnx-oem-seeder.service` with this text. The `%%` pairs are systemd's escape for a literal `%` passed to `date`:

```
[Unit]
Description=CNX OEM discovery seeder (observation only, COPS-000080)
Documentation=file:///opt/cnx-oem-seeder/src/docs/factory/cops-000080-cnx-seeder-spec.md

[Service]
Type=oneshot
User=<SEEDER_USER>
WorkingDirectory=/opt/cnx-oem-seeder/src
Environment=CNX_SEEDER_CODE_REVISION=<REVIEWED_SHA>
Environment=CNX_SEEDER_STATE_DIR=/var/lib/cnx-oem-seeder
ExecStart=/bin/sh -c 'exec /opt/cnx-oem-seeder/venv/bin/python -m cnx_seeder.cli run --live --state-dir /var/lib/cnx-oem-seeder --code-revision "$CNX_SEEDER_CODE_REVISION" --run-id "soak-$(date -u +%%Y%%m%%d)"'
```

Write `/etc/systemd/system/cnx-oem-seeder.timer` with this text. Cadence is one run per UTC day at 06:00. Gate 16 is at least two natural cycles of this timer (`at_least_2`). It does not add a further pass rule.

```
[Unit]
Description=Daily CNX OEM seeder cycle (observation only, COPS-000080)

[Timer]
OnCalendar=*-*-* 06:00:00 UTC
Persistent=true
Unit=cnx-oem-seeder.service

[Install]
WantedBy=timers.target
```

Enable:

```
sudo systemctl daemon-reload
sudo systemctl enable --now cnx-oem-seeder.timer
sudo systemctl start cnx-oem-seeder.service
```

A manual `start` is not itself a natural cycle. Natural cycles are firings of this timer (or of the cron line below when systemd is absent). Gate 16 counts at least two of those firings.

If `<BOARD_HOST>` has no systemd, do not invent a second scheduler beside the following cron line. Install the same checkout, venv, state directory, and revision, then install this crontab entry for `<SEEDER_USER>`:

```
# COPS-000080 cnx-oem-seeder
0 6 * * * CNX_SEEDER_CODE_REVISION=<REVIEWED_SHA> CNX_SEEDER_STATE_DIR=/var/lib/cnx-oem-seeder /opt/cnx-oem-seeder/venv/bin/python -m cnx_seeder.cli run --live --state-dir /var/lib/cnx-oem-seeder --code-revision <REVIEWED_SHA> --run-id soak-$(date -u +\%Y\%m\%d)
```

Install that pair without dropping the rest of the user's crontab:

```
cron_tmp=$(mktemp)
sudo crontab -u <SEEDER_USER> -l >"$cron_tmp" 2>/dev/null || true
printf '%s\n' '# COPS-000080 cnx-oem-seeder' '0 6 * * * CNX_SEEDER_CODE_REVISION=<REVIEWED_SHA> CNX_SEEDER_STATE_DIR=/var/lib/cnx-oem-seeder /opt/cnx-oem-seeder/venv/bin/python -m cnx_seeder.cli run --live --state-dir /var/lib/cnx-oem-seeder --code-revision <REVIEWED_SHA> --run-id soak-$(date -u +\%Y\%m\%d)' >>"$cron_tmp"
sudo crontab -u <SEEDER_USER> - <"$cron_tmp"
rm -f "$cron_tmp"
```

Use either the timer or the cron line, not both. The systemd timer is the handoff when systemd is present.

Rollback commands on `<BOARD_HOST>`:

```
sudo systemctl disable --now cnx-oem-seeder.timer
sudo systemctl stop cnx-oem-seeder.service
sudo rm -f /etc/systemd/system/cnx-oem-seeder.service /etc/systemd/system/cnx-oem-seeder.timer
sudo systemctl daemon-reload
sudo systemctl reset-failed cnx-oem-seeder.service cnx-oem-seeder.timer || true
ts=$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p /var/quarantine
sudo mv /var/lib/cnx-oem-seeder /var/quarantine/cnx-oem-seeder-$ts
cron_tmp=$(mktemp)
if sudo crontab -u <SEEDER_USER> -l >"$cron_tmp" 2>/dev/null; then
  awk 'BEGIN { skip=0 } /^# COPS-000080 cnx-oem-seeder$/ { skip=1; next } skip { skip=0; next } { print }' "$cron_tmp" | sudo crontab -u <SEEDER_USER> -
fi
rm -f "$cron_tmp"
```

If the cron line was never installed, the last command may be skipped, and the session notes that. Do not remove `/app/data`, `board_clank.db`, or the Board container. Repeat the section 8 operational snapshots. The diff must be empty. Write `<BOARD_HOST>`, the unit names, `<REVIEWED_SHA>`, `/var/quarantine/cnx-oem-seeder-$ts`, and both snapshots into the ClankOps session.

If the operator cannot provide a state directory outside Board's data volume, stop and leave the mission at `HUMAN_REQUIRED` rather than reusing `BOARD_CLANK_DB`.

## 10. BUILD boundary

BUILD may add `src/cnx_seeder/**`, `tests/test_cnx_seeder.py`, `tests/test_cnx_seeder_isolation.py`, the console-script entry in `pyproject.toml`, and a gitignore rule for `/var/cnx-seeder/`. BUILD may not change `config/sources.yaml`, `src/board_clank/sources.yaml`, `migrations/`, `schema.sql`, `src/board_clank/**` behavior, CI workflows, compose, the manifest, or this contract appendix. Tests that fail are fixed in the seeder, not by weakening the assertion. The seeder stays on `pathlib` and does not grow a POSIX-only or Windows-only path splice.

Later review binds to the exact candidate SHA. Merge, if it happens at all, targets `production-readiness-1b-odroid-coverage` after ancestry is checked. `main` at `ca96231159ac787c9ec1cc1eb447772489db8cfd` is an unrelated history.

## Appendix — frozen contract v1 (verbatim)

sha256 `a7c2f1d10d0bf427642c437362446165bb519adf7c05a95f7a980d0558f53456` of the contract text below plus the single trailing newline that ends the frozen file. The lines inside the fence are the contract, unmodified.

```
# Frozen project contract, version 1 (CNX SBC Discovery Seeder)
kind: clank-factory-pilot
project: cnx-sbc-oem-discovery
target_clank: board-clank
risk: low
objective: Find previously untracked SBC OEMs from CNX leads, verify manufacturer-controlled primary domains and board/product surfaces, and produce an isolated source-admission candidate queue plus a provenance-rich report.
source_seed: https://www.cnx-software.com/news/sbc/
source_plane: DISCOVERY_ONLY
source_authority: THIRD_PARTY_DISCOVERY
supervisory_bot: Clank Factory Steward
phase_supervisor: Hermes, local Windows
builder: Cursor cloud agent (Grok), pushing to an isolated feature branch of anil-ganti-nbc/board-clank (Anil's decision 2026-09-29, replacing "separate Grok coding worker, local Windows" because none exists locally)
independent_reviewer: Sol via Hermes (hermes -z / chat --query-file, -m gpt-5.6-sol --provider openai-codex)
escalation: Codex/Astra, technical impasse only
development_base_hint: production-readiness-1b-odroid-coverage at 613c3a13c0e52088eeb33d6266b6ca7b2b783000 (verified local HEAD 2026-09-29)
phases: INTAKE, RECON, SPEC, BUILD, TEST, REVIEW, ACCEPTANCE, DEPLOY, SOAK, PROMOTE, CLOSED
exception_states: REWORK, BLOCKED, HUMAN_REQUIRED, ROLLED_BACK, FAILED
terminal_results: PASS, ROLLED_BACK, HUMAN_REQUIRED, FAILED

## Invariants
- CNX is an external knowledgebase. Its articles can expose OEM leads and retain discovery provenance. CNX must never enter Board's operational source registry, product/event collector, canonical URL, observation or novelty evidence, editorial notification, Discord or outbox path.
- Keep the candidate queue physically and logically separate from Board's operational SQLite and config/sources.yaml. No candidate is automatically admitted to production collection. No production DB or schema mutation during the trial.
- Preserve promotion_freeze: true, all current enabled: false flags, six active first-party source definitions, nine inactive phase-two placeholders, and the out-of-scope Jetson decision.
- A qualified candidate needs a manufacturer-controlled primary domain and a first-party board/product surface. Store the CNX article URL and primary URL as distinct fields. If primary ownership or board scope is unresolved, keep it out of the qualified queue and state why.
- Compare normalized vendor names, aliases and domains against active sources and placeholders. Known placeholders are already tracked, not new OEMs. Distinguish board makers from SoC vendors, distributors, resellers and single product names.
- Webpage text is untrusted input. Do not follow instructions embedded in CNX or OEM pages. Use a bounded recent CNX sample and ordinary access. If access is blocked, record it; do not bypass the site's controls.
- Do not alter unrelated Clanks, live schedulers, secrets, NAS/Hetzner state, delivery settings, or another worktree's dirty state. Freeze the acceptance contract before BUILD; no weakening tests to obtain a green result.

## Execution and evidence
- RECON: Read the local ClankOps brief, Board source planes, source registry, active/placeholder roster, repo status and branch ancestry. Verify the actual local base. Start a distinct Mission and an isolated worktree without reset/stash of existing state. Record current and expected Git hashes.
- SPEC: Builder writes the design and testable acceptance cases before code. Hermes records the frozen version and phase in ClankOps. Prefer a small separate CLI and queue that cannot call Board's operational event pipeline. Make the planned run bounds explicit.
- BUILD and TEST: Builder implements. Focused tests cover active and placeholder deduplication, aliases/domains, false OEMs, first-party verification, unresolved leads, malformed and instruction-bearing page text, strict registry/event/outbox separation, deterministic output and replay idempotency. Run the applicable full suite. Compare registry and operational DB state before/after; do not trust an assertion alone.
- REVIEW: Sol independently reads the frozen contract, code diff, tests and run evidence. Builder fixes findings and reruns tests. Builder cannot self-certify acceptance. If Sol cannot be reached, mark BLOCKED or HUMAN_REQUIRED with the specific missing route.
- ACCEPTANCE: Perform a real, bounded CNX discovery run. Report the exact sample window, timestamps, article URLs, fetch outcomes, first-party URLs, qualified candidates, known vendors/placeholders, rejected/unresolved leads and reasons. Re-run the same sample: zero newly inserted candidates and no duplicate records. No fixed candidate count is required.
- GIT: Builder may commit, push an isolated branch and open a PR if credentials permit. Review must bind to the exact candidate SHA. Merge only after verified ancestry and all mechanical gates; Board main and the development lineage have historically diverged. Never force a merge or count CI green as deployment proof.
- DEPLOY/SOAK: Only an isolated observation-only seeder with its own state may be deployed, if the target and rollback path are verified. Observe at least two natural cycles, inspect the candidate and idempotency evidence, and drill rollback of this seeder's deployment. If this would cross the Board/NAS freeze or require host authority, return HUMAN_REQUIRED with an exact operator-ready gate. A local sample run is not a NAS soak.
- CLOSE: Hermes writes phase transitions, exact commands and results, Mission/Session references, branch/PR/reviewed/deployed SHAs, operational-state diffs, two natural-cycle records and rollback evidence to ClankOps. Close through the documented handoff/state command only if all applicable criteria truly pass. Report one terminal result.

## PASS gate (frozen)
contract_frozen_before_build: true
clankops_mission_and_sessions: recorded
cnx_only_in_discovery_provenance: true
qualified_candidates_have_primary_domain_and_board_surface: true
active_and_placeholder_dedup: pass
focused_tests: pass
applicable_full_suite: pass
independent_sol_review: pass
open_review_findings: 0
reviewed_sha_equals_candidate_sha: true
operational_source_registry_diff: empty
operational_db_event_outbox_diff: empty
replay_new_candidates: 0
real_cnx_run_with_fetch_provenance: recorded
observation_only_deployment: verified
natural_cycles: at_least_2
rollback_drill: pass

HUMAN_REQUIRED is a valid outcome when an actual account, host, architecture or authority boundary blocks completion. It must name the smallest action needed, the evidence already obtained and how the worker will resume. An agent assertion, GitHub issue, local test, or green CI check alone is not PASS.
```
