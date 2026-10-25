# Phase 3b: Fix over-linking and audit the calibrations (blocks Phase 4)

Reviewer findings on Phase 3 (pipeline, tests 153/153 and the log check pass; the scorer numbers reproduce):
1. Over-linking. On the full 518 run, 18 INCOMPLETE rows have 40 to 85 steps (samples top out at 14). Different people (for example user_42 and user_49, and user_75, user_79, user_80) get IDENTICAL linked resource sets (93 resources: 5 by identity_key, 88 by reference_closure). Two people cannot own the same 88 records. `reference_closure` in linker.py follows ANY shared link key transitively, so it leaps across persons through shared values inside large comprehensive snapshots. This creates findings on other people's data (decoys), which must never happen, and it can flip statuses.
2. 24 COMPLETE rows have zero steps (a COMPLETE needs evidence-backed verification steps; samples have 1 to 6). They need a cause per case.
3. Several calibrations rest on one sample each: shared_context always True (8 uses), a text-based ANALYTICS_PROFILE to MARKETING_PROFILE override, a support_replica service-based attachment rule, tombstone handling. 225 of 518 cases hit at least one policy fallback.
4. The scorer is code/evaluation/main.py, not scorer.py (fine; document it in the README).

Run `git pull --rebase` first, then paste the block.

````text
You are the build agent for HackerRank Orchestrate October 2026, "Ghost Data Still Exists". This is PHASE 3b, a fix-up of Phase 3. Same logging rules as before (AGENTS.md section 5, bracketed headers, tool=Claude Code, exact model ID, log check before the final answer, no keys, never open .env). Scope: ONLY the items below. No Phase 4 work, no model calls. All Phase 3 rules (no hardcoded IDs, D15, D17, no time/ID-pattern links, sample_output.csv only in code/evaluation/) still apply.

TASKS
1. Fix reference_closure (code/audit/linker.py).
   a. Diagnose first: for case_51 and case_77 print which link key bridged each hop (shape only: key type, how many resources share it, which evidence file). Report the bridging key types.
   b. Replace the transitive any-shared-key closure. A resource may be linked by reference only when an already linked resource EXPLICITLY references it: a field whose value is a resource id of a known prefix shape (for example a source or parent resource id), directed from the linked resource to the target, ONE hop only (state the depth in a comment and a constant). Never traverse through emails, phones, hashes, user_ids, names, agent or order references, cohorts, statuses, regions, or any value shared by more than one person's identity set. Add a hub guard: a key shared by resources that carry different persons' identity values is never a bridge.
   c. Keep the PRD sense of rule 4 ("referenced by a linked resource, for example an export that points to a search document") and nothing broader.
   d. Tests: a synthetic comprehensive snapshot where person A's record shares an agent email, a cohort and a region with 20 other people's records links none of them; a directed one-hop reference links its target; a two-hop chain does not; the hub guard; a reference to another person's resource (that record has another person's identifier) is NOT linked. The gateway test still passes.
   e. Add a global invariant check (a test over all 518 cases plus a line in the sanity run): a resource linked to two different user_ids must be linked to each through its own identity_key or same_document match, never through reference_closure. Print how many resources violate it (must be 0) and the per-case distribution of linked resource counts before and after.
2. Re-run all 518 cases and report before/after: status counts, how many cases change status, how many rows exceed 14 steps and why (each remaining one must be justified by distinct person-linked evidence), the scorer table on the samples (must not get worse except for removing false links), and link_check.
3. Zero-step COMPLETE cases (24 before the fix). For each, print: number of linked resources, whether ANY of the person's identifiers (emails, phones, hashes, user_id) appear as raw text in any evidence file visible at audit_at (count only, no values), and which formats. Classify each as (a) nothing exists about the person in visible evidence, (b) identifiers appear but nothing was linked (a parser or linker gap: list the formats and fix generically), or (c) other. Do not invent steps. Report the counts per class. If class (b) is non-empty, fix it generically and re-run.
4. Calibration audit. For each of these report the number of the 518 cases that take each branch and the evidence fields used, and replace any rule that rests on text matching or a single sample with a rule grounded in a data field or the policy text:
   - shared_context for SUPPORT_MESSAGE: find real evidence fields that indicate shared customer, agent or order context (agent, order or reference fields, conversation participants). Implement a real predicate. If no field exists, keep the safest interpretation and say so.
   - ANALYTICS_PROFILE to MARKETING_PROFILE override: justify it from the resource prefix and system mapping (marketing_ prefix) or remove the text-based override.
   - support_replica service-based SUPPORT_ATTACHMENT rule, ACCOUNT_TOMBSTONE handling, restore_allowed from log vocabulary: show the evidence field each uses and the branch counts.
   - the policy fallbacks: break down the 225 cases by fallback reason and predicate; list the three most common reasons with their counts and say what they default to.
5. Document in the README that the scorer is `python code/evaluation/main.py`.
6. Quality gates: pytest code/tests -q, python code/main.py --no-ai, the scorer, python claude_terminal/log_tools.py check, staged-diff scan for gsk_, AIza, sk- and api_key=. Commit and push to origin (my fork) only. Do not commit output.csv.

EXIT CRITERIA (PASS/FAIL each): the bridging keys diagnosed; closure restricted with decoy tests; the cross-person invariant reports 0 violations; no case above 14 steps without a justified reason; zero-step COMPLETE cases classified with counts; calibration branch counts reported and text-based/single-sample rules replaced or justified; before/after statuses and scorer reported; log check passes; no secrets; nothing from Phase 4 exists.

FINAL ANSWER FORMAT (short, pasteable): PASS/FAIL per criterion; bridging key types; before/after table (status counts, status flips, rows over 14 steps, scorer metrics); zero-step classes with counts; calibration branch counts; any decision you need from me. Then stop and wait for my go-ahead.
````
