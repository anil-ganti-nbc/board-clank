# Manual ROCK 5B documentation-reference POC

This is a bounded DOCUMENTATION plane, not another PRODUCT adapter. It retains the maintained first-party ROCK 5B Hardware Design revision assertions on `https://docs.radxa.com/en/rock5/rock5b/download`. ROCK 5B+, software, certificates, forums and other vendors/pages are excluded. No PDFs or arbitrary linked URLs are fetched.

## Identity and scope

The exact ROCK 5B tab and official `dl.radxa.com/rock5/5b/docs/hw/` artifact paths establish the document's model context. Admission then resolves an existing `radxa` Board with the exact marketed name and canonical PRODUCT URL. It verifies PRODUCT source registration, disabled state, first-source provenance, identity-key consistency, canonical/current pointer consistency and payload hash. Missing, multiple, wrong-vendor, nonboard or forged targets fail closed. There is no new Board, revision, variant or SoC creation by documentation admission.

Hardware revision labels remain literal source assertions. V1.42 and V1.423 can point to the same artifact. Duplicate identical URLs collapse within each assertion, but that does not establish separate files or relabel hardware from a filename. URL aliases are not assumed byte-identical. Document version and effective hardware date stay UNKNOWN. The parser accepts balanced hardware panels with explicit tab labels; missing/ambiguous/truncated structures and any wrong-scope artifact fail closed. It deliberately favors retained uncertainty over broad scraping.

## Semantic namespace contract

The additive `EntityKind.DOCUMENTATION_REFERENCE` makes typed EventRecord validation honest. This is a generic model contract addition. The DB schema remains v3. Reference keys use `reference:<source>:<sha256(canonical page, linked Board, hardware label)>`; identity keys are separate. Canonical/reference-current/occurrence rows use this entity kind, and carry an existing Board link plus UNKNOWN revision/variant links. They never enter `boards`, `board_revisions`, `board_variants`, novelty or PRODUCT current rows.

New and changed documentary evidence records only NEW_REFERENCE audit events, always `baseline_silent=1`, with `market_novelty=false` and UNKNOWN effective dates. No notification row is created. Stable content adds sightings, exact successful replay writes nothing, and conflicting run-ID reuse is refused. Historical discoveries after source baseline remain silent. Missing headings/pages do not imply removal/EOL and do not delete old reference state. Changed notes or newly explicit labels are retained as documentary transitions, never current FIELD_CHANGED/BOARD_REVISION/NEW_BOARD.

Semantic hashes include the hardware label, normalized note content and canonical artifact pointers. Transport, navigation, sidebar, heading anchor names, software releases, other tab content, link captions and duplicate links are excluded. Whitespace, host case, fragment and the allowlisted `download=1` query are cosmetic. Other queries, credentials/ports, lookalike hosts, encoded/traversing paths and wrong-model links are refused. Redirect targets are checked before following. Filename/path changes remain distinct pointer evidence unless verified as an alias; no content equality is invented.

## Registration and consumer compatibility

Only the marked isolated qualification DB receives the local `radxa-rock5b-documentation-poc` SourceRecord: vendor Radxa, DOCUMENTATION, FIRST_PARTY_SUPPORTING, disabled, REGISTERED, EXPERIMENTAL. Existing definitions are validated, never silently repaired or enabled. Admission also requires all DB sources disabled and no promotions. The global 16-row config roster, six-PRODUCT manifest, promotion freeze and ordinary `collect` dispatch remain unchanged.

The common-base manifest validator accepts only `*-product` sources. This POC intentionally stays outside that admitted declaration; promoting/integrating documentation into a future generic manifest is a separate gate. No manifest authority is bypassed. Core observer v0.2 remains unchanged and reports the actual 17 isolated source rows. Config health still counts the 16 declared rows; these are distinct facts. Board/variant counts and reports query graph tables and exclude references. Current PRODUCT reads qualify entity kind. There is no projection/rebuild subsystem in Board Clank; reference current reconstruction is tested by joining current to canonical rows and recomputing payload hashes.

SQLite online backup and verified restore preserve reference rows in existing tables. The legacy metadata table-count list omits observation_occurrences; qualification explicitly compares that table too, rather than treating metadata counts as sufficient proof. Observer read-only file-byte stability, legacy CLI reads, PRODUCT replay and typed reference-event reconstruction are tested.

## Manual use

Run from Todd's isolated worktree with its `src` on PYTHONPATH. A new directory is required for initialization; existing unmarked directories and existing capture names are refused. No default/canonical DB path is used. The new workspace owns its fresh `qualification.db`, marker and captures. Live initialization seeds an existing PRODUCT entity via the unchanged Radxa PRODUCT parser from one fetched canonical product page; subsequent passes fetch only the exact documentation page.

```powershell
$env:PYTHONPATH = 'src'
python -m board_clank.collectors.radxa_documentation --qualification-root '..\evidence\radxa-live' --run-id pass1 --experimental-live
# Invoke passes separately, manually:
python -m board_clank.collectors.radxa_documentation --qualification-root '..\evidence\radxa-live' --run-id pass2 --experimental-live
python -m board_clank.collectors.radxa_documentation --qualification-root '..\evidence\radxa-live' --run-id pass3 --experimental-live
```

Omit `--experimental-live` for deterministic packaged fixtures and use a distinct new qualification root. Live fetches are bounded GETs with strict first-party redirect checks. HTTP/header/native metadata is retained alongside semantic hashes, without treating Last-Modified as hardware chronology. Failed documentation fetches record failed attempts and errors, without baselines, receipts, entity mutation or diagnostic closure.

No scheduler, source enablement, promotion, delivery, production/NAS access or deployment. All retained captures and DBs belong to the isolated qualification workspace. A subsequent explicit user instruction authorizes a normal push of this isolated branch after qualification; no integration, main/Astra push or PR is authorized.

Live capture persistence writes the original HTTP response bytes directly. It never uses a Windows text-mode write to substantiate a raw-body hash. A byte/hash equality regression covers mixed CRLF/LF and UTF-8 text. Qualification must compare every saved live page's SHA-256 and size to its HTTP metadata before considering the capture qualified.

## Fixture provenance

`fixtures/radxa_documentation/rock5b-hardware.html` is the actual 2026-10-03 first-party Hardware Design section reduced by removing unrelated content and adding HTML/body wrappers. It retains both model tabs for firewall qualification. Source and original hash are in its manifest. Radxa Computer (Shenzhen) Co., Ltd. publishes the documentation under CC BY 4.0; attribution and changes are recorded there. The offline PRODUCT seed is copied unchanged from the exact common-base Radxa fixture (`rock5_5b.html`, first-party URL and 2026-09-22 observation recorded in that corpus). Packaged fixture copies match the repository corpus. Adversarial/cosmetic/new-reference variants are explicit offline test transformations, not claimed upstream changes.
