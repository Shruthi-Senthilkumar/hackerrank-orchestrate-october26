# Phase 2b Report: Fixing the Linker Recall Gap

Generated from `code/evaluation/link_check.py` after adding trace correlation
(`code/audit/linker.py`'s `trace_correlation` rule, fed by `code/audit/evidence/log_parser.py`'s
`TraceHint` extraction). No personal-looking values below; shapes, counts, and resource-id-style
placeholders only.

---

## 1. Diagnosis of all 44 originally-missing pairs

Phase 2's report incorrectly stated that every sample resolves through direct identity keys. The real
split of the 44 missing (system_id, resource_id) pairs (before this phase's fix) was:

- **24 coverage-based** — the resource never appears in any visible Observation at all. Correct proof is
  "a covered store doesn't list it", which is Phase 3's job, not the linker's. Unchanged by this phase.
- **20 observed but unlinked** — a visible Observation of the exact resource exists, but no rule
  connected it to the person. **8 of these 20 are now fixed** by the new `trace_correlation` rule (see
  §2); **12 remain genuinely unexplained** after an exhaustive, evidence-only investigation (see §3).

### 1a. The 20 observed-but-unlinked pairs, before the fix

| Case | Resource | File(s) holding it | Identifiers on that record | What else shares a key with it |
|---|---|---|---|---|
| case_03 | `analytics_platform`/`analytics_NNNN` | 1 log line (`resource_lookup_trace` family) | none (lookup_key/email/phone/hash all literal `null`) | same `trace_id` as one other log line, also all-null |
| case_04 | `analytics_platform`/`analytics_NNN` | 1 JSON record (`customer_analytics_report` family) | none (user_id/email/phone/email_hash all JSON `null`) | no shared key with anything else visible |
| case_10 | `support_platform`/`support_NNN` | 1 log line of a 3-line trace (`support_replica` family) | none on this line | **same `trace_id` as a `contact_query_started` line carrying `lookup_key`** |
| case_12 | `account_service`/`account_NNNN` | 1 log line (`service_events` family) | none on this line | **same `trace_id` as a `profile_lookup_started` line carrying the person's `lookup_key` email** |
| case_15 | `integration_service`/`data_flow_NNNN` | 1 log line (`service_events` family) | none on this line | **same `trace_id` as a `connector_config_read_started` line carrying `subject_key`** |
| case_15 | `security_service`/`audit_record_NNNN` | 1 log line (`service_events` family) | none on this line | **same `trace_id` as an `audit_record_query_started` line carrying `subject_ref`** |
| case_17 | `account_service`/`account_NNNN` | 1 log line (`service_events` family) | none on this line | **same `trace_id` as a `profile_lookup_started` line carrying `lookup_key`** |
| case_17 | `backup_service`/`backup_NNNN` | 1 log line (`service_events` family) | none on this line | **same `trace_id` as a `restore_policy_check_started` line carrying `subject_key`** |
| case_19 | `account_service`/`account_NNNN` | 1 log line | none | same `trace_id` as a `profile_lookup_started` line with `lookup_key` |
| case_19 | `security_service`/`audit_record_NNNN` | 1 log line | none | same `trace_id` as an `audit_record_query_started` line with `subject_ref` |
| case_21/25/26/27/28 | `account_service`/`account_NNNN` (×5) | 1 JSON record each (`service_resource_export`, `profile_lookups` collection) | none (`profile: null`, `status_code: 404`) | no shared key — see §3 |
| case_21/25/26/27/28 | `analytics_platform`/`analytics_NNNN` (×5) | 1 JSON record each (`service_resource_export`, `profiles` collection) | none (every identifier field explicit JSON `null`) | no shared key — see §3 |

Rows in **bold** (8 pairs: case_10, case_12, case_15 ×2, case_17 ×2, case_19 ×2) are fixed by trace
correlation (§2). The remaining 12 rows (`case_03`, `case_04`, and the 10 `service_resource_export`/
analytics rows) are addressed in §3.

### 1b. The possible false link, investigated (case_17)

Case_17 both missed `account_service/account_NNNN` (expected) and linked an **extra**
`account_service/account_MMMM` (not in the sample's step list). Investigated whether `account_MMMM` was a
false positive:

- `account_MMMM`'s log line: `resource_id=account_MMMM event=profile_lookup_completed rows=0 http_status=404`,
  trace `tr-X`.
- The **opening line of trace `tr-X`** (same file): `event=profile_lookup_started lookup_key="<this
  case's own email>"`.

**Conclusion: not a false link.** `account_MMMM` is linked by the exact same grounded mechanism as the
now-fixed `account_NNNN` (trace correlation on a real, matching email) — it is a second, genuinely
real account-lookup for this person that also returned not-found. The sample's minimal step list simply
only cites one of the two. This is the same category as the 7 "extra" pairs already noted in Phase 2's
report (real links the sample didn't need to cite), not a defect.

---

## 2. Trace correlation (`code/audit/linker.py`'s `trace_correlation` rule)

**Mechanism**, implemented as a generic structural relationship, never a special case tied to any
specific case/resource/ID:

1. `code/audit/evidence/log_parser.py` now extracts a `TraceHint(trace_id, value, event_time, source_id)`
   from **every** log line that carries a `trace_id` and an identifier-like value — regardless of whether
   that same line also has a `resource_id`. (A `profile_lookup_started` line has the identifier but not
   yet a resolved resource; the later `_completed` line has the resource but usually not the identifier.)
2. `code/audit/evidence/registry.py`'s new `visible_trace_hints(reg, time_view)` gates each hint by
   **both** its file's manifest visibility (D15) **and** its own line's `event_time <= audit_at` — a
   stricter, line-level check specific to this rule, so a trace's identifying line from after the cutoff
   is ignored even though the file itself is otherwise visible.
3. `code/audit/linker.py` builds, per case, the set of trace_ids whose hinted value matches this
   identity, then links any resource-bearing Observation that shares one of those trace_ids, with
   rule name `trace_correlation`.

**Keys surveyed across all 10 real log families** (code comment in `log_parser.py` records this):

- **`trace_id`** — the only key actually reused across multiple lines in this dataset; used by 9 of the
  10 families (not `cloud_runtime_export`, which nests its own escaped key=value structure differently).
- **`requestId`** (the `cloud_runtime_export` family's analogous field) — checked, and found to be
  **unique per line** (every value appears exactly once in a sample file), so it is never a correlation
  key here and was not implemented as one.
- **`correlation_id`** — does not appear anywhere in the dataset at all.
- Identifier-bearing keys found on trace-opening lines: `lookup_key`, `subject_ref`, `subject_key`,
  `subject_reference`, `correlation_key`, `match_key`, plus any value shaped like an email under any key
  name. All are treated uniformly by `_identifier_values()`, not as per-case special cases.

**Result:** 9 `trace_correlation` links across the 32 samples, fixing 8 of the 20 observed-but-unlinked
pairs (one, case_17's `account_MMMM`, was already an "extra" — see §1b).

**Decoy and safety tests** (`code/tests/test_trace_correlation.py`): a synthetic trace whose opening line
carries the target's real email links its resource line with `trace_correlation`; a synthetic decoy trace
with the **same resource type** but **another person's** identifier does not link; a trace whose
identifying line is dated after `audit_at` is ignored even though its file is visible; an injected
instruction-like string in an unrelated field is stored as opaque data and never changes which resource
links to whom.

---

## 3. The 12 pairs with no grounded connection — reported, not invented

Per the task's instruction, these are listed with exactly what was checked, not guessed at.

**Pattern A — `service_resource_export` verification snapshot, 10 pairs** (`case_21/25/26/27/28`, one
`account_service` `profile_lookups` entry + one `analytics_platform` `profiles` entry each):

- The `account_service` record is a 404 (`profile: null`), the `analytics_platform` record has every
  identifier field explicit JSON `null`. Neither carries `trace_id` (this file format has no trace
  concept — it is a flat array per service/collection, not a log stream).
- Checked: the activity claims for both resource_ids (`DELETE_RECORD`/`ANONYMIZE_RECORD`) — neither
  carries an email or `user_id` in its `details` text.
- Checked: all 12 `LINK_RESOURCE_IDENTITY` activity rows — none mention any of these 10 resource_ids.
- Checked: every other evidence file for a raw-text occurrence of each resource_id. **In 7 of the 10
  cases** (`account_5684`, `account_3866`, and the 5 `analytics_NNNN` ids), the resource_id **does** also
  appear in `customer_data_snapshot_bundle_20260917.json` — and that earlier bundle's `customer_profiles`
  record genuinely does carry the person's real name/email, confirmed to be the same `user_id` as the
  case in two spot checks. **But that bundle's own manifest `captured_at` (2026-09-17T12:00:00Z) is after
  these cases' `audit_at` (2026-09-15T12:00:00Z)** — D15 says that file is simply not visible yet, and
  using it would mean citing evidence captured after `audit_at`, which every rule in this project
  forbids. The identifying evidence exists; it just wasn't allowed to exist yet, in-world, when this
  audit ran.
- **Conclusion: genuinely unexplained from visible evidence.** No time-window, number-pattern, or
  ordering heuristic was used to bridge this (explicitly forbidden); none was found that isn't one of
  those three. Flagging for your decision rather than inventing a rule.

**Pattern B — fully anonymized/null record, no later identifying snapshot exists at all, 2 pairs**
(`case_03`'s `analytics_9406`, `case_04`'s `analytics_901`):

- `case_03`: both log lines of the resource's own trace have `lookup_key=null`/`email=null` etc. — the
  trace-correlation mechanism correctly found nothing to propagate, because there is nothing there.
- `case_04`: the one JSON record (`customer_analytics_report` family) has every identifier field `null`;
  no other evidence file anywhere in the dataset (visible or not) mentions `analytics_901`.
- **Conclusion: genuinely unexplained**, and unlike Pattern A, there is no later file where the real
  identifier even exists — these specific analytics records appear to have never carried an identifier
  in any evidence the participant can see, at any time.

**What was checked and ruled out for all 12, to be explicit:** `LINK_RESOURCE_IDENTITY` activity, every
other evidence file's full text for the literal resource_id, shared `trace_id` (where applicable), the
`customer_data_snapshot_bundle` family specifically (since it is the one format proven to carry
pre-anonymization identifiers elsewhere), and the PDFs' extracted text. No ID-number pattern (e.g.
`account_5684` near `user_26`) and no "nearby timestamp in the same batch" heuristic was used, per the
rule against time-window/number-pattern/ordering links.

---

## 4. Re-run results

| Metric | Phase 2 (before) | Phase 2b (after trace correlation) |
|---|---|---|
| Overall recall | 0.604 (67/111) | **0.676 (75/111)** |
| Total extra pairs | 7 | 7 |
| D15 default vs. alternative | identical | **still identical** (0.676 both ways) |
| `identity_key` links | 92 | 92 |
| `activity` links | 0 | 0 |
| `trace_correlation` links | n/a (rule didn't exist) | **9** |
| `reference_closure` links | 0 | 0 |

The D15 default and the inner-timestamp alternative remain identical on the 32 samples even with trace
correlation added (trace hints are always gated at the stricter per-line `event_time` regardless of which
D15 variant is active, so this comparison was unaffected by the new rule).

**Remaining gap, split as requested:**

- **24 coverage-based** (expected, Phase 3's job — see Phase 2's report §5 for why: every one of these is
  a `VERIFY_RECORD_ABSENT`/`PRESENT` step whose correct proof is "a covered store doesn't list it", not a
  direct observation to link).
- **12 unexplained** (listed in full in §3 above, with what was checked). These need your decision: either
  confirm they are intentionally unreachable from participant-visible evidence at these cases' `audit_at`
  (in which case Phase 3 should treat them the same as a coverage gap it cannot resolve either, i.e. an
  "unknown" state handled by the safest compliant interpretation), or tell us what connection we're
  missing.

---

## 5. The five Phase 2 open questions — decided

1. **Coverage-based absence/presence inference is Phase 3's job.** Confirmed. Phase 2's linker only
   connects a person to Observations that exist; `policy.py`/`decision.py` will cross-reference
   `Coverage` records against a person's known resource categories.
2. **Logs get no blanket Coverage record; a log proves only the exact resource it names.** Confirmed —
   unchanged from Phase 2's design (see `log_parser.py`'s module docstring).
3. **`ACTIVE_DATA_FLOW` stays as an internal sentinel category, never emitted in `output.csv`.** Confirmed
   — it is a detector concern (PRD 7.6), not one of the 15 `deletion_rules.csv` categories, and
   `code/audit/mapping.py` already documents this.
4. **Keep the `activity` and `reference_closure` rules; add a per-rule counter for the full 518-case run
   later.** Confirmed — both rules remain implemented and tested even though 0 samples exercise them
   (518-case behavior may differ; `link_check.py` already prints `rule_counts` per run, ready to extend
   to the full set in Phase 6).
5. **Keep the 2 irregular PDFs as raw text for now.** Confirmed, but flagging a direct consequence found
   while answering "which evidence ids in the sample answers are PDFs or images": **of the 13 distinct
   evidence_ids cited across all 32 sample answers, exactly one is a PDF (`evidence_58`,
   `delivery_correction_attachment.pdf`) and zero are images.** `evidence_58` is cited by `case_07` for a
   `support_platform`/`support_001` `REPORT_REMAINING_RECORD` finding — and that PDF's extracted text
   (profiled in Phase 1/2: "reference CS-4827 / support_001", a name, an email, "apartment number... call
   before delivery") directly contains both the resource id and an identifier. Because this PDF is
   currently treated as irregular (raw text only, 0 Observations), `support_001` does not appear in any
   Observation at all right now, so `case_07` cannot resolve this finding without either a future PDF-
   parsing pass or a Phase 3-level text search over the raw PDF text this parser already returns. No
   images are cited by any sample, so the "keep images unread until Phase 4" decision has no sample-level
   cost today.
