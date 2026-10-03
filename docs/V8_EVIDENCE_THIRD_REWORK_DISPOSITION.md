# Board v8 evidence-plane third review rework disposition

Mission COPS-000096. Source-only scoped repair of the independent Sol
REQUEST_CHANGES review of `0da9b99a92feb3b7840c3af46e7a14e0730aa0ab`
(tree `fd4747313b78f05041f7767260d83c3ff3affde6`). The five findings were
confirmed against that committed source. Some review line numbers referred
to a normalized packet and differ from repository lines; the bytes match.
No finding was dismissed, and no sibling branch was integrated.

## Repair disposition

1. FriendlyELEC and Khadas now preserve required discovery/product roles;
   Khadas also preserves marketing role. Their bounded redirect handlers
   validate every hop and final URL before reading a body. Discovery indexes
   retain their selected route. Allowed same-role redirects use their validated
   final URL for discovery, marketing, purchase lookup and PRODUCT parsing.
   Fetch/parser/role failures clear all drafts. Empty resolved results cannot
   pass as successful PRODUCT evidence; non-board rejection requires an
   explicit heading, reason and NON_BOARD_CATALOGUE_ITEM role. First-party
   scope and existing model/variant/SoC laws remain unchanged.
2. Supporting receipts use `supporting-input-v2:<sha256>` in the existing
   schema-3 TEXT field. They authenticate source, target, unresolved state,
   sorted claims and the complete parsed-info semantic projection, including
   full mapping, model/status, ignored models and artifact crosslinks. Only
   decoded_text_sha256 is excluded as raw transport evidence. Diagnostic
   state uses that same projection. Transaction admission revalidates the
   complete (target,mapping), including changes that leave the target unchanged.
   Reused IDs with changed semantics and unversioned legacy receipts fail
   before mutation; legacy IDs are not silently blessed as exact replays.
3. PRODUCT admission checks both trusted registry and durable source row for
   disabled, EXPERIMENTAL, REGISTERED, non-placeholder and in-scope state,
   in addition to canonical plane/vendor/authority. These checks precede
   successful admission, replay lookup and failed-run recording. Supporting
   authority cannot enter PRODUCT admission.
4. The runtime lock now pins PyYAML 6.0.2, satisfying the existing distribution
   minimum. Exact-SHA CI checks the updated pin and runs pip check after
   project installation; the container build also runs pip check. Python
   >=3.12 and schema 3 declarations remain unchanged. Local unfiltered tests
   use the recorded installed interpreter/packages; exact pinned Python 3.12
   environment qualification belongs to separate exact-SHA CI receipts.
5. Observer schema_revision reports the observed migration version, UNKNOWN
   when unknown, and the binary expectation separately. Every non-COMPATIBLE
   existing database state is degraded and durable table projections are
   withheld; missing database state stays UNKNOWN. Corrupt or structurally
   unreadable state has conservative results without writes or migration.

## Evidence and remaining gates

The precommit targeted collector and new boundary suite completed with 109
passed in 73.22 seconds, actual process exit 0. It covers per-hop/final-body
guards, final parser/marketing provenance, partial fetch/parser/empty-result
failures, durable and trusted source-state drift before all writes, supporting
semantic and legacy receipt collision no-ops, transaction mapping changes,
observed v1/v2/v3/newer/empty/partial/fresh/corrupt schema states and observer
byte stability. Evidence is retained separately from this source worktree.

This disposition does not claim exact-final full-suite, live, CI, independent
review or acceptance success. Those gates require their own actual-process
receipts bound to the final committed SHA/tree. Previous live/test reports are
historical evidence for their named execution commits and are not carried
forward to this candidate. The prior second-rework no-blocker and metadata
assessment was superseded by the independent findings above.

No schema migration, source enablement, promotion, scheduler/delivery change,
runtime/NAS mutation, main merge, CNX action or deployment was performed.
ESTOP and AFK policy were preserved. An independent model approval alone
does not pass acceptance or complete the Mission.
