# Phase 2 Report: Identity, Evidence Parsing, Linking, Replica Drift

Generated from `code/audit/evidence/registry.py` (the parse table), `code/audit/identity.py`,
`code/audit/reconciler.py`, and `code/evaluation/link_check.py`. No personal-looking values below;
shapes and counts only.

---

## 1. Parse table (all 94 evidence files)

| Format | Files | Observations | Coverage records | Unparsed lines | Errors |
|---|---|---|---|---|---|
| sql | 24 | 891 | 116 | n/a | 0 |
| json | 28 | 948 | 206 | n/a | 0 |
| log | 26 | 1336 | 0 (see note) | 0 | 0 |
| text | 1 | 41 | 0 | n/a | 0 |
| pdf | 4 | 7 (2 regular PDFs parsed; 2 irregular PDFs report text+shape, 0 observations) | 0 | n/a | 0 |
| image | 11 | 0 (deferred to Phase 4's vision model, not guessed) | 0 | n/a | 0 |
| **Total** | **94** | **3223** | **322** | **0** | **0** |

Every one of the 94 evidence files is parsed (79 into Observations, 11 images explicitly deferred with a
reported row rather than silently skipped). Zero parse errors, zero unparsed log lines.

**Logs get no blanket Coverage record** (by design, see `code/audit/evidence/log_parser.py`'s module
docstring): a log is a stream of individual events, not a dump of a whole collection, so it can only prove
the state of the exact `resource_id` a line names — which a plain Observation (`exists=True`/`False`)
already captures. This is an open question for Phase 3, below.

Caching: `code/audit/evidence/registry.py` caches the full parse to `.cache/evidence_registry.json`,
keyed by a hash of every evidence file's bytes plus every parser module's source, so a rerun after any
code or data change is automatically invalidated. Warm-cache rebuild: ~0.06s; cold parse of all 94 files:
a few seconds.

### 1a. Carry-over fix from the Phase 1 review

`code/evaluation/profile_report.md` section 5 previously said "16 families"/"15 distinct families" for the
26 log files; the real grouping by name stem is **10 families** (`application_trace`, `cloud_runtime_export`,
`notification_delivery`, `operations_stream`, `resource_lookup_trace`, `search_index_diagnostic`,
`service_events`, `structured_service_events`, `support_replica`, `syslog_archive`). Fixed in both the
profiler (`code/tools/profile_dataset.py`'s `LOG_FAMILY_STEMS`, now the single source of truth that
`code/audit/evidence/log_parser.py` also uses) and the report text.

### 1b. Carry-over fix: SQL statement counter and comments

`sql_sandbox._count_statements` previously tracked only single/double quotes, so an apostrophe inside a
`--` comment (or a `;` inside a `/* ... */` block comment) could desync it. Rewritten to also track line
and block comments; a hostile-comment test (`test_statement_count_ignores_apostrophe_inside_line_comment`,
`test_statement_count_ignores_semicolon_and_quote_inside_block_comment`,
`test_hostile_comment_with_apostrophe_does_not_desync_the_real_sandbox`) covers this in
`code/tests/test_sql_sandbox.py`.

### 1c. Carry-over fix: dead code in timeview.py

Removed three unused names nothing referenced: `RawDataAccessError`, `_GUARDED_LOADER_NAMES`,
`TimestampDisagreement`. The gateway test (`code/tests/test_gateway_rule.py`) still passes, and now also
exempts `code/audit/evidence/registry.py` (see its module docstring) for the one legitimate, documented
reason a module outside `loaders.py`/`timeview.py` needs to enumerate the raw evidence manifest: a global,
case-independent ingestion pass (PRD 7.2), with the actual per-case time gate still enforced downstream by
`visible_observations`/`visible_coverage`.

A second, unplanned gateway fix was needed while building this phase: `code/audit/identity.py`'s as-of
reconstruction legitimately needs to see audit-log entries on *both* sides of a reference timestamp (to
"undo" a post-cutoff change and recover the pre-cutoff value), which the existing `TimeView.visible_audit_log()`
cannot provide by design. Added `timeview.all_audit_log_entries()` — still routed through `timeview.py`,
documented as the one sanctioned way to get the unfiltered log — instead of letting `identity.py` call
`loaders.load_user_audit_log()` directly.

---

## 2. Identity statistics (F03)

| Metric | Value |
|---|---|
| Total request emails (518 + 32 samples) | 550 |
| Resolved to a user_id | 550 (100%) |
| Resolved via current email | 447 |
| Resolved via a historical (old_value) email | 103 |
| Ambiguous (matched more than one user_id) | 0 |
| Unresolved | 0 |

Every request email resolves. Verified against the full dataset: `test_all_518_plus_32_request_emails_resolve`
in `code/tests/test_identity.py`. `email_hash` matches `sha256(lowercased email)` for all 850 current
identities (`test_email_hash_matches_sha256_for_every_real_identity`).

As-of-audit_at reconstruction is tested on synthetic data for both branches described in the Phase 2
instructions: an event after `audit_at` is undone (`test_as_of_reconstruction_undoes_events_after_audit_at`)
and an earlier value is correctly recovered when the only relevant event is still in the future relative to
`audit_at` (`test_as_of_reconstruction_keeps_earlier_value_with_no_relevant_events_yet`).

---

## 3. Linker (F06) rule counts, measured on the 32 samples

| Rule | Count |
|---|---|
| `identity_key` (direct email/phone/hash/user_id match) | 92 |
| `activity` (LINK_RESOURCE_IDENTITY activity row) | 0 |
| `reference_closure` (referenced by an already-linked resource) | 0 |

Both the `activity` and `reference_closure` rules are implemented and unit-tested with synthetic decoys
(`code/tests/test_linker.py`), including a 3-way near-identical-name decoy test proving a name alone never
links (two decoys sharing most of a target's name but a different email/account are correctly excluded).
Neither rule fires on the 32 public samples — every sample case happens to resolve purely through a direct
identity-key match. This is worth watching on the 518-case evaluation set, where PRD 3.2 fact 7 says
`LINK_RESOURCE_IDENTITY` activity exists specifically to resolve harder cases (e.g. `object_` /
`support_` attachments with no email of their own, or a `source_resource_id` cross-reference like
`search_documents_primary`'s decoy triplet profiled in Phase 1).

---

## 4. Replica drift (F07, decision D5)

| Metric | Value |
|---|---|
| SQL files checked (all 24) | 24 |
| Files with a primary/replica pair (two-table shape) | 13 |
| Files with drift found | 12 of 13 |
| Total drift records | 13 |
| Direction | 13 of 13 are "present in replica, absent from primary" |

Every drift found in the real dataset is the ghost-data direction the challenge is about: a replica still
holding a record the primary has already deleted (zero cases of the reverse — a replica missing a record
the primary still has). `evidence_54` (`customer_accounts_failover_replica_20260902.sql`) shows
`account_005` present in the failover replica but absent from the primary, matching the PRD's own
Appendix C illustrative example. Tested on synthetic drift and no-drift fixtures plus a real-file smoke
test (`code/tests/test_reconciler.py`).

---

## 5. link_check.py summary (32 samples, `code/evaluation/link_check.py`)

| Metric | D15 default | D15 alternative (inner timestamp also gates visibility) |
|---|---|---|
| Overall recall | 0.604 (67/111) | 0.604 (67/111) |
| Total extra pairs | 7 | 7 |

**The two visibility rules give identical results on the 32 samples.** Every nested JSON-bundle snapshot's
own `captured_at` is always `<=` its file's manifest `captured_at`/`exported_at` (confirmed in Phase 1
profiling), so gating on the stricter inner timestamp never excludes anything the looser manifest-time
rule includes, on this sample set. D15's default (manifest time only) stands as coded; Phase 4/6 should
re-run this comparison on the full 518-case set before treating it as fully settled.

### Why recall is 60%, not higher — read before Phase 3

**All 24 "missing" pairs that are not reproducible from any visible evidence are `VERIFY_RECORD_ABSENT`,
`VERIFY_RECORD_PRESENT`, or future-remediation verification steps — never a `FINDING` with a concrete
evidence citation.** Example: `case_01` (COMPLETE) expects one step,
`VERIFY_RECORD_ABSENT account_service/account_001` citing `evidence_54`. `evidence_54` is a *coverage*
file — a full primary-table dump that simply does not list `account_001` among its rows. Phase 2's linker
can only connect a person to an Observation that *exists*; there is nothing to link when the correct answer
is "this resource is absent, proven by a covered store that doesn't mention it." That inference —
cross-referencing a person's known resource categories against `Coverage` records with no matching
`Observation` — is exactly the policy/decision layer's job (PRD modules `policy.py`/`decision.py`), which
Phase 2 is explicitly scoped not to build. The 24 gap pairs are listed in full in the script's output; they
are not a Phase 2 defect, but Phase 3 must be told about them, which is why task 7 asked for this list.

The 7 "extra" linked pairs (6 `legal_service`/`ORD-XXXX` from the `legal_retention_register` PDF, plus one
`account_service` resource in `case_17`) are all genuine links the person really has — the sample's minimal
step list simply didn't need to cite them (e.g. a compliant retained legal hold may not need its own
verification step in every case shape). Not a linker defect; Phase 3's planner decides which linked
resources become reported steps.

---

## 6. Open questions for the user

1. **Coverage-based absence/presence inference belongs to Phase 3.** Confirm this is the intended
   architecture (Phase 2 = raw linking only; Phase 3 cross-references `Coverage` + a person's linked
   resource categories to infer "absent because covered and not found" / "present and retained"), so
   Phase 3's `policy.py`/`decision.py` design can proceed on that basis.
2. **Logs get no Coverage record** (section 1 above) — confirm this default is correct, or whether a log
   family should instead produce a bounded coverage claim (e.g. "this log proves `account_lookup` queries
   for the covered time window show no hit for resource X").
3. **`data_flow_` has no `deletion_rules.csv` category** (it is a detector concern per PRD 7.6, not one of
   the 15 rule rows); `code/audit/mapping.py` currently labels it `ACTIVE_DATA_FLOW` as an internal
   sentinel, not a real category name. The shift-handover text file instead prints `DATA_FLOW` as its
   human-readable label for the same resources. Confirm `ACTIVE_DATA_FLOW` is fine to keep as-is for
   Phase 3's detectors, since it is never meant to appear in `output.csv`'s `category`-shaped data anyway.
4. **`activity`/`reference_closure` linker rules are unexercised by the 32 samples** (section 3). Both are
   implemented and synthetically tested; flagging in case the 518-case evaluation run surfaces a real case
   that needs them and they need recalibration.
5. **PDF text extraction for the 2 irregular PDFs** (`account_history_report_*.pdf`,
   `delivery_correction_attachment.pdf`) returns raw text and a "not regular" flag rather than Observations,
   per the Phase 2 instructions ("leave interpretation to me"). Both do mention a concrete `user_NN` and
   `support_NNN`/order reference plus an email in free-text form; decide whether Phase 3 (or a later pass of
   this parser) should do a best-effort regex extraction from them, or whether they stay citation-only via
   their raw text.
