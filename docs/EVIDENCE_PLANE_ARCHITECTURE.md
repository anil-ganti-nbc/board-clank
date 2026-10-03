# Evidence-plane architecture gate (COPS-000093)

Common base: `613c3a13c0e52088eeb33d6266b6ca7b2b783000`. This document precedes implementation. Todd owns this isolated tranche; Astra owns Foundation 7A FriendlyELEC. Integration is a later, dedicated pass.

## Empirical representation failure

The live [Radxa ROCK 5B resource page](https://docs.radxa.com/en/rock5/rock5b/download) has a Hardware Design section with separate ROCK 5B and ROCK 5B+ tabs. ROCK 5B has revision headings V1.3, V1.41, V1.42, V1.423, V1.44, V1.45 and V1.46; some carry component change notes, others link drawings. These are reference claims about revisions, not complete Board/SoC/port/variant observations. Revision effective dates are not supplied by these headings. HTTP Last-Modified is page transport metadata, not revision chronology. The shared page's other tab warns that a schematic is stale. Model and section boundaries matter.

`evidence/common-base-model-probe.json` outside the worktree captures an actual baseline-model experiment in an isolated DB. A documentation draft with ROCK 5B's exact identity and one revision claim replaced the PRODUCT BOARD current hash (`9edac442...` -> `11323e4a...`) and added an unsupported SILENT revision with UNKNOWN SoC. SOC_CHANGED, PORTS_CHANGED, BOARD_REVISION and NEW_VARIANT were recorded even though this was a documentation baseline. The probe used the unmodified exact common-base implementation. No canonical DB was used.

The cause is concrete: `Pipeline._admit_observation` always upserts the Board/revision/variant graph, and `_sync_entity` shares one current pointer per entity across planes. Filling a sparse document's UNKNOWN fields with PRODUCT values still changes page/native fields, creates artificial variants, and makes documentation part of the authoritative current snapshot. Marking a draft historical suppresses novelty but does not preserve PRODUCT authority. Marking it insufficient discards useful linked evidence. An adapter must not call this path for a reference.

## Bounded choice

Use one Radxa DOCUMENTATION proof of concept, limited to ROCK 5B Hardware Design revision references. Accept only the exact download URL and the explicit ROCK 5B tab. The ROCK 5B+ tab, software images (including third-party links), certificates and other documentation pages stay outside this collector. No PDF contents are fetched or inferred; an artifact URL is a pointer, not a parsed specification.

Linkage needs the exact tab label, explicit official model-bearing download paths in that panel, and an existing PRODUCT-owned `radxa:rock-5b` entity with the exact product URL/name and in-scope Board type. No fuzzy names, URL-number identity, free board creation or cross-vendor updates. Missing/conflicting signals fail closed and remain unresolved evidence. Two headings pointing to one PDF remain distinct source assertions; neither is silently relabelled from the PDF filename.

## Adapter-local handling, no generic migration

Use the existing schema's TEXT entity-kind columns and canonical/occurrence/current tables to store a separate `DOCUMENTATION_REFERENCE` namespace. Its durable key is source + canonical page + explicit board + section/revision ID. The record's `board_key` links to an existing entity; Board/revision/variant graph, PRODUCT current pointers and novelty rows are untouched. This namespace is source-scoped supporting evidence, never an alternative Board identity.

The collector and reference admission live in one bounded manual POC module. No changes to generic pipeline, domain models, schema, migrations, PRODUCT adapters, global source roster, taxonomy or default CLI collection dispatch are needed. One disabled EXPERIMENTAL supporting source row is registered only in the explicitly isolated qualification DB. The existing roster remains unchanged. Namespace use is a data contract, documented here; consumers must distinguish references from entities.

Every newly discovered reference baselines silently, including historical discoveries after the first source pass. A changed reference is a suppressed NEW_REFERENCE audit transition with explicit source-observation chronology; it is never FIELD_CHANGED, BOARD_REVISION, EOL or market novelty. Unknown effective dates stay UNKNOWN. This POC deliberately qualifies evidence retention and linkage, not automatic revision promotion. Repeated semantic payloads add sightings only; exact run replay writes nothing. Failed fetch/parse/linkage cannot mint or mutate entities or infer removal.

## Compatibility and qualification

Schema remains version 3: no migration requirement. Existing online SQLite backup copies these rows in the same tables; restore and replay must preserve them. Observer v0.2 already reads source/run/diagnostic/event counts without decoding entity-kind enums. Verify unchanged contract shape and read-only byte stability; capture the new disabled source and diagnostics honestly. A reference report provides mappings/hashes/unresolved evidence separately from the stable core observer shape.

Qualification requires deterministic reduced first-party fixtures, ambiguity and vendor isolation tests, exact replay, stale historical claims, genuine reference-content changes, PRODUCT state equivalence, backup/restore, full pytest summary and actual exit 0. Three manual live passes use one isolated DB, retained HTTP pages/headers/raw hashes and semantic hashes, exact mappings, unresolved links, event/diagnostic/novelty/outbox snapshots. Passes 2-3 must produce no semantic transitions absent upstream change.

No scheduler, promotion, delivery, production deployment, NAS mutation, push or PR. The admitted runtime is not inspected or changed. Later integration conflicts are assessed only from Todd's file list/common base, never Astra's unfinished state.

## Reviewed continuation: semantic enum compatibility gate

The parent reviewed this research gate and authorized continuation on 2026-10-03. Before implementation, an executable compatibility probe showed `EntityKind('DOCUMENTATION_REFERENCE')` raises `ValueError`. `EventRecord.entity_kind` uses that enum. Raw SQL insertion alone would bypass the typed semantic contract even though existing observer/backup SQL accepts the TEXT value. Masquerading as BOARD or REVISION would misrepresent reference identity. The smallest justified generic addition is therefore **one additive EntityKind.DOCUMENTATION_REFERENCE enum member**, so reference events can use the existing validated EventRecord model. This supersedes the earlier proposal to leave taxonomy entirely unchanged; no generic pipeline/model/schema change or migration is required.

Audit of existing consumers: canonical/current lookup in Pipeline always qualifies `(entity_kind, entity_key)`; Board reports/counts use `boards` and `board_variants`; health/observer read counts/source/run summaries without converting arbitrary entity kinds; backup snapshots/copies the existing tables; there is no independent projection/rebuild subsystem in this repository. Reference current state uses its own kind plus an explicit `reference:` key prefix and source/URL/model/revision identity hash. Tests must reconstruct typed events and reconstruct reference current hashes from their linked canonical observations, verify unchanged PRODUCT current rows, back up/restore all rows including occurrences, and exercise legacy report/observer/PRODUCT replay against a DB containing references. The global source roster and manifest remain unchanged; observer sees the isolated POC's extra disabled source row, while config-based health's registered count still describes the 16 declared sources. This distinction must be reported honestly.
