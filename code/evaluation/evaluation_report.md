# Evaluation report

**The 32 public samples (`dataset/sample_deletion_requests.csv` / `sample_output.csv`) are the only labelled data available to this submission.** All metrics below are measured on them; the 518 real cases have no golden answer available to participants.

## Case-level and row-level accuracy

- Case-level status accuracy: 1.000 (32/32)
- Row exact match (status + full step set, order-insensitive): 6/32 (0.188)
- Sequence accuracy (exact ordered step list): 0.188

## Step-level accuracy

- Step precision (without evidence_id): 0.940
- Step recall (without evidence_id): 0.819
- Step F1 (without evidence_id): 0.875
- Step precision (with evidence_id): 0.940
- Step recall (with evidence_id): 0.819
- Field-level accuracy (phase/state/step_no on matched steps): 0.897
- Citation accuracy (evidence_id on matched steps): 1.000

## Error taxonomy

- Missed steps (expected, not produced): 35
- Extra steps (produced, not expected): 10
- Wrong status: 0
- All 35 originally-missed sample steps (Phase 3 investigation) were traced individually to a specific D17 cause: either zero observations anywhere in visible evidence, an identity-less 404 or fully-anonymized record (D17's own named examples), or evidence captured after that case's audit_at. None were parser/linker bugs. The step-level ceiling is below 100% by design (D17).
- Wrong-treatment / wrong-evidence / wrong-order sub-counts are not broken out separately in this pass (time-boxed cut per the final-phase prompt's own priority list, item 3); every extra/missed step is individually explained in the Phase 2b/3/3b/4 commit messages and DECISIONS.md instead.

## Intent (F13)

- 44 authored synthetic cases (code/evaluation/intent_cases.md): rule layer alone 26/42 (0.619), Qwen alone 39/42 (0.929), combined pipeline 42/42 (1.000) on the 42 non-ambiguous cases.
- All 32 public samples classify DELETE.
- All 518 real cases: 10 NOT_APPLICABLE (all English), 0 rule/Qwen disagreements, 0 flagged unresolved (code/evaluation/intent_review.md) -- matching D10's own ~10-case prediction.

## Images (F05)

- 11/11 images read (OCR grounding + two Gemini readers). Second reader used on 2 of 11 (the rest fell back to the grounded primary reader alone and are flagged as such, never guessed).
- A resource-id shape bug was found and fixed: a reader extracted a UI label ("Delivery tracking") as if it were a resource id; grounding alone did not catch it since the label is genuinely visible on screen. Fixed by also requiring a known mapping.py prefix shape.
- D16 re-checked against all 11 images: no SECONDARY_IDENTIFIER or PRODUCT_TELEMETRY found.
- Full per-image counts in code/evaluation/extracted_image_facts.md.

## Custom evaluation cases (authored by us, not from the dataset)

Built as synthetic module-level inputs in code/tests/test_custom_evaluation_cases.py; no dataset files are used. Each runs the real decision, detector and planner modules.

| Case | Input | Expectation | Result |
|---|---|---|---|
| A: replica drift | A USER_PROFILE record that a replica still holds although the primary lacks it | Violation, status INCOMPLETE, steps REPORT_REMAINING_RECORD, DELETE_RECORD, VERIFY_RECORD_ABSENT | PASS |
| B: compliant tombstone, audit, analytics | A redacted tombstone with no direct identifier, a security audit record within retention, an analytics record already unlinked | No violation, status COMPLETE, only VERIFY_RECORD_REDACTED / VERIFY_RECORD_PRESENT / VERIFY_RECORD_ABSENT steps, every step cites evidence | PASS |
| C: active flow and restorable backup | An enabled data flow, a restore-allowed backup, and a dependent USER_PROFILE record | INCOMPLETE; DISABLE_DATA_FLOW and BLOCK_RESTORE come before DELETE_RECORD; verification covers all three | PASS |
| D: non-deletion request | Intent is not a deletion request | NOT_APPLICABLE with steps [] regardless of any resource state | PASS |

## Security (I1-I8)

| Test | Description | Result |
|---|---|---|
| I1 | Instruction text in a log line | PASS -- byte-identical facts |
| I2 | Instruction text in a JSON field | PASS -- byte-identical facts |
| I3 | Instruction text in a PDF text layer | PASS -- byte-identical facts |
| I4 | Instruction text rendered on an image | PASS (live-only, gated behind --run-live-ai) |
| I5 | Injection in request_text, English + Spanish | PASS -- never authorizes deletion; a genuine request is not suppressed by an appended injection |
| I6 | Hostile SQL (ATTACH/PRAGMA/trigger) | PASS -- rejected by the sandbox (test_sql_sandbox.py) |
| I7 | Request naming another person's data | PASS -- only the resolved subject's records link |
| I8 | Secret scan on log.txt | PASS -- no secret-shaped pattern found |

**Attack success rate: 0/8 (0%).**

## Failures found and improvements made

Sourced only from DECISIONS.md, phase reports, and log.txt:

1. A literal `"null"` placeholder (an absent log field, not JSON null) was read as a real identifier, creating a massive cross-person link hub via reference_closure (D18).
2. An off-by-one pipe split in the operations_stream log parser shifted every field by one, turning a component name into a fake shared trace_id -- a second, independent cross-person hub.
3. Hash-seed nondeterminism in state.py's tie-break for same-timestamp facts, fixed with a deterministic secondary sort key; proven byte-identical across 4 PYTHONHASHSEED values.
4. The original transitive, any-shared-key reference_closure (D18) was replaced with a directed, one-hop, hub-guarded, conflicting-identity-guarded rule.
5. Two more trace-key gaps found while classifying zero-step COMPLETE cases: cloud_runtime_export's `requestId` and syslog_archive's 3rd header token were real, reused correlation keys never wired into trace_correlation.
6. Calibrations replaced with field-grounded rules: SUPPORT_MESSAGE shared_context now checks ticket_id/message_excerpt instead of "any text"; the MARKETING_PROFILE override dropped its redundant text-matched disjunct.
7. A sentence-scope bug in the intent rule layer: a negation in an injected second sentence could retroactively flip a genuine deletion request in the first sentence -- fixed by evaluating each sentence independently (found via I5 security testing).
8. A UI-label-as-resource-id bug in image extraction, fixed with a mapping.py prefix shape check layered on top of OCR grounding.
9. Found in this phase's own review: `python code/main.py --no-ai` crashed on a clean checkout because model results existed only in the git-ignored `.cache/`. Fixed with the committed code/replay/ cache (this phase's task 1), proven keyless and byte-identical to the live run.
