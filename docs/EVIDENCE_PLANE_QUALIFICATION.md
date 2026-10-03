# Existing-vendor evidence-plane qualification — COPS-000093

Todd's bounded Radxa ROCK 5B DOCUMENTATION POC passed offline regression, three separately invoked live passes, exact replay, observer/backup/restore checks and package qualification on 2026-10-03. No canonical Board DB or NAS runtime was accessed. No source was enabled, promoted, scheduled or given delivery authority.

## Provenance and isolation

- Mission: `COPS-000093`, Board Clank first-party evidence plane expansion; UUID `01a1009a-6725-7103-8a03-450aa0d83c25`.
- Final qualification Session: `01a100ca-d654-7083-9394-f6c030da14d3`. Earlier real Sessions `01a1009a-6726-72db-b0cd-cd278a58e4ae` and `01a100ab-5df2-746e-affd-e6db445855a2` ended with explicit PAUSED handoffs; this resumes the same appropriate Mission.
- Exact common base: `613c3a13c0e52088eeb33d6266b6ca7b2b783000`.
- Todd branch: `evidence-planes-existing-vendors`; worktree: `C:\Users\anil\Documents\Codex\2026-10-03\task\board-evidence`.
- Research decision commit: `d524836910792737a1ed35f01e0c46c73b5842f3`, parent exactly the common base.
- Initial implementation: `c15f18cada439e9eb97baf77eb207de7635fc621`.
- Qualified code and live execution SHA: `58a199b599826ca359ddaa350220c671d038ba54`; tree `b685fc46b27ed9b89791917a8f92b538b6871ce0`.
- Final reporting commit changes documentation only. Its SHA/tree and remote equivalence are recorded in the external final evidence packet; no history was amended.

Canonical ClankOps was inspected before repo mutation. COPS-000074 and COPS-000080 were not reused or changed. Astra's FriendlyELEC Foundation 7A remains independently owned: no inspection, merge, rebase or consumption of its worktree/branch/Mission/state, including any subsequently completed state. The ClankOps Store bridge captures Git evidence from Todd's worktree only, avoiding the ordinary CLI's canonical-checkout inspection side effect.

## Research and architecture decision

[EVIDENCE_PLANE_CENSUS.md](EVIDENCE_PLANE_CENSUS.md) contains the six-vendor empirical surface census, all requested attributes, explicit unknowns, first-party ownership links, rejections, priorities and claim-scoped authority matrix. [EVIDENCE_PLANE_ARCHITECTURE.md](EVIDENCE_PLANE_ARCHITECTURE.md) records the actual common-base sparse-document experiment and typed enum failure before implementation. Research preceded coding and was checkpointed for parent review.

Raspberry Pi PIP already locates regulatory/design/PCN/lifecycle documents, but full document facts are incompletely parsed; future enrichment is preferable to another duplicate adapter. Orange Pi documentation has useful manual/pin/interface evidence but current fetch qualification remains weak. Radxa maintained docs add explicit revision/component notes absent PRODUCT. Banana Pi maintained docs add variant/revision detail but require model crosslinks rather than opaque numbered URLs. Hardkernel lifecycle statements distinguish production discontinuation/suspension from stock. PINE64 grouped schematics and exact store SKUs expose useful scoped conflicts, while the nonboard firewall remains essential.

The selected POC uses only `https://docs.radxa.com/en/rock5/rock5b/download`, Hardware Design, exact ROCK 5B tab. Seven explicit labels are retained: V1.3, V1.41, V1.42, V1.423, V1.44, V1.45 and V1.46. Component notes make this materially stronger revision evidence than PRODUCT; official model-bearing download paths and an existing validated PRODUCT target make linkage bounded. ROCK 5B+ is deliberately excluded: it is another model/tab with different artifacts and stale-schematic context, not a title alias. PDF bodies, software, compliance, historical wiki duplication and broad announcements remain out of scope.

Exact vendor-qualified model/tab/artifact paths plus PRODUCT name, canonical URL, provenance and payload hashes link `REFERENCE_TO_BOARD` to `radxa:rock-5b`. No fuzzy names, fake Board IDs or URL-number identity are used. Missing, multiple, wrong-vendor, nonboard or forged targets fail closed. References cannot mint or modify Board/revision/variant/SoC entities.

The only generic model contract addition is `EntityKind.DOCUMENTATION_REFERENCE`. The existing enum rejected this value, so raw SQL alone would evade typed EventRecord validation. One additive member is the smallest honest contract extension. `models.py`, generic pipeline, SQL schema/migrations, PRODUCT parsers, ordinary collection dispatch, source roster, manifest, observer and delivery policy are unchanged. Schema remains v3. Older typed consumers must receive the enum addition before validating reference events; the baseline raw-SQL observer remains compatible.

## Fixtures and offline tests

Two deterministic fixtures exist in both repository and packaged data: the reduced actual first-party ROCK 5B Hardware Design section (both tabs retained for firewall testing) and the unchanged exact-common-base PRODUCT seed. The manifest records URL, observation, original hash, reduction, attribution and CC BY 4.0 documentation provenance. Adversarial and cosmetic variants are explicit offline transformations, not claims of upstream changes.

The required laws cover silent historical backfill (including after source baseline), exact replay, explicit cross-plane linkage, ambiguity closed, duplicate documentation preserving all PRODUCT state, deterministic genuine documentary transitions, rejected stale announcement URLs and ignored old announcement navigation, vendor isolation, scope/provenance/URL/redirect safety, honest fetch failures, atomic rollback, typed event/current reconstruction, legacy CLI summaries and all-table backup/restore equality.

| Qualification | Actual result | Evidence outside Git |
| --- | --- | --- |
| Exact common-base regression | 268 passed in 92.70s; pytest exit 0 | `evidence/baseline-pytest-receipt.json` (tool-observed summary) |
| Final full regression on SHA `58a199b…` | **318 passed in 184.00s (0:03:04); actual pytest process exit 0** | `evidence/pytest-full_bytes.txt`, `evidence/pytest-full_bytes-receipt.json` |
| Byte persistence regression | 1 passed; actual pytest exit 0 | `evidence/pytest-capturebytes.txt`, receipt |
| Archive-based wheel build | Actual backend exit 0 | `evidence/package-build/build.stdout.txt`, verification |
| Offline CLI using unpacked wheel | Actual process exit 0; 7 resolved mappings | `evidence/package-build/offline.stdout.json`, verification |

Final full command: `python -m pytest -p no:cacheprovider --basetemp C:\Users\anil\Documents\Codex\2026-10-03\task\pytest-full_bytes -ra`. Complete stdout and subprocess return code are retained. Early test/command failures were corrected; earlier receipts remain evidence history, never substitutes for the final successful run. The final reporting commit is documentation-only; qualified code is unchanged.

The wheel contains both new fixtures with bytes equal to repository package data. Wheel SHA-256: `feb5e982ded27225f1788044535b8c7fbdaf76d7bd4b46f11990138fe49996ba`. Build used a tracked Git archive in a separate local directory, with no network or global package install.

## Three-pass live soak

All final passes ran SHA `58a199b…` against the same newly created isolated DB at `C:\Users\anil\Documents\Codex\2026-10-03\task\evidence\radxa-live-bytes\qualification.db`. Each was invoked separately, and its full state was saved before the next. First pass seeded one existing PRODUCT Board via the unchanged official PRODUCT parser and then fetched documentation; subsequent passes fetched documentation only. SQLite connection and file/network audits found zero forbidden or canonical-checkout accesses. Only exact first-party GETs occurred (2, 1, 1).

| Evidence | Pass 1 | Pass 2 | Pass 3 |
| --- | --- | --- | --- |
| Observed UTC start | 08:09:26 | 08:13:25 | 08:14:13 |
| Actual process exit | 0 | 0 | 0 |
| Resolved revision-reference mappings | 7 | 7 | 7 |
| Unresolved links / diagnostics / errors | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| NEW_REFERENCE audit events added | 7, all silent | 0 | 0 |
| Reference occurrences retained | 7 | 14 | 21 |
| FIELD_CHANGED / market novelty | 0 / 0 | 0 / 0 | 0 / 0 |
| Documentation notifications / eligible outbox | 0 / 0 | 0 / 0 | 0 / 0 |

Shared semantic SHA-256: `bee852a08cba6cb49d4fd243b2b822df99684af2006c57b765588ff98382e8b5`.

PRODUCT graph/current/canonical/occurrences, novelty, classifications, variants, support, prices and notification rows stayed equal across all three passes. PRODUCT current rows remain owned by `product-seed`. Combined PRODUCT-state digest: `358c2c9148ca3ed68e9eb7da0bd1ec125c28cf01d4e2d9c16135095f2c9a62cf`. Offline tests additionally compare before/after documentation admission, including initial admission. Four suppressed, undelivered PRODUCT baseline notification rows are retained; **total notification rows are not zero**. No documentation notification row is created.

Each saved original response's size and SHA-256 exactly matches HTTP capture metadata and independent reparse. All documentation responses are 59,921 bytes, HTTP 200, with no redirect. Their raw hashes differ:

- Pass 1: `1575eb16b5dc33e9e4bf56a9f138aee6f5caeae9da799c33f9ced6bc48a4f038`.
- Pass 2: `3b415ff13551001bf912f1f9bb3aad0b350e3ab7816979c89e62153d60c30781`.
- Pass 3: `3aee4c4ac09712fc83bffcca6151fb989ebef2485ece699ce094086ac716a2fe`.

The independent byte comparison establishes the difference as injected Cloudflare request/timestamp parameters and order of its two footer scripts. After normalizing those parameters and sorting only those footer scripts, all remaining HTML bytes match. Original files remain intact; the parser ignores scripts. HTTP Last-Modified is September 30 at 06:44:02 for pass 1 and 06:44:00 for passes 2–3. This transport metadata is not a hardware/document effective date; both remain UNKNOWN. No freshness refresh was used.

Earlier `radxa-live` text-mode captures failed raw-byte provenance because Windows changed line endings. They are explicitly superseded, retained for audit, and count as **zero qualified passes**. Only the three `radxa-live-bytes` passes count.

## Observer, replay and restore

Unchanged observer v0.2 reports COMPATIBLE schema v3, 17 actual disabled isolated sources, four runs/receipts, zero execution errors and no diagnostic conditions. Declared config remains 16 sources; the unchanged manifest remains six PRODUCT sources. The extra supporting POC row is local qualification data, not admitted production source expansion. `code_revision` is qualified SHA; `deployed_source_sha` is UNKNOWN, not a deployment claim.

Observer read leaves the original DB file SHA unchanged at `fe4af588d8643e58f3a6883b9b48f65d5f1b83fa5870bd98cbadb7b26efdf6c2`. Final observer equals the last run's capture and the restored DB's observer. Exact pass-3 replay changes neither any SQL table nor the DB bytes, even with a different observation-time argument. Verified SQLite backup/restore compares **all** tables, explicitly including observation_occurrences omitted by the legacy metadata count list; restored replay is also a no-op. Integrity is `ok`. Backup file SHA-256 is `6e2dc25ddec31e18ba358744d401d7041f833787e388ee5c389106e586e990e3`.

## Self-review and later integration

Self-review checked Todd's changed-file list against the exact common base, the entire new admission module, source/linkage validation, parser boundaries, transaction paths, replay fingerprints, URL/redirect policy, event reconstruction tests, fixtures and package-data change. No SQL/schema/pipeline/Product source/manifest/observer/runtime change is hidden. New references are source-scoped supporting history and never compete for durable Board identity. New or changed historical reference evidence always carries `baseline_silent=1`; no automatic current revision or lifecycle claim is made. Missing evidence is not deletion/EOL.

Known bounded limits: one Board/tab only; no PDF bodies or alias byte verification; no verified effective dates; strict model-first PRODUCT provenance may leave future cross-source entities unresolved; all later discoveries remain silent until a separately reviewed dated editorial model exists. ROCK 5B+ exclusion is explicit coverage debt. The seven source labels are assertions, not seven unique artifacts or seven proven manufactured revisions.

Expected integration overlap, inferred only from Todd's files/common base: `pyproject.toml` package-data may also receive FriendlyELEC fixture additions; retain both during a dedicated integration pass. `taxonomy.py` has the additive kind and needs typed-consumer review if another tranche changes it. Todd's new collector/tests/docs/fixture directory have distinct names. No actual Astra diff or conflict was inspected. Combined source/manifest counts, regression, consumer contract and qualification require a later integration owner; Todd has not integrated or deployed either tranche.

Final ClankOps completion must record the exact clean final commit, authorized normal branch push and verified matching remote SHA. Canonical Mission/Session closure receipts and the final SHA/tree are retained with the external evidence packet. This tranche does not reopen COPS-000074, touch COPS-000080 or create another Mission.
