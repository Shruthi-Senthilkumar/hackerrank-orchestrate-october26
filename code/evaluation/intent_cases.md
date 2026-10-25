# Intent classification: authored synthetic test cases (Phase 4 task 4b)

44 cases authored by hand (none copied from dataset/deletion_requests.csv or dataset/sample_deletion_requests.csv), covering every language family found in the real data (en, es, fr, pt, ja, ko), negations, limiting scope, mixed-language text, indirect phrasing, deletion-verification requests, and prompt-injection attempts. 2 are genuinely ambiguous (`UNCLEAR` expected) and excluded from the accuracy denominator below.

## Per-layer accuracy

| Layer | Correct | Total | Accuracy |
|---|---|---|---|
| Rule layer alone | 26 | 42 | 0.619 |
| Qwen alone | 39 | 42 | 0.929 |
| Combined pipeline (rule + Qwen + escalation) | 42 | 42 | 1.000 |

`UNCLEAR`-labeled cases (genuinely ambiguous) are excluded from the correct/incorrect count for every layer -- any answer is acceptable there; they are still shown below with what each layer actually said.

The `error?` column flags only a wrong COMBINED-pipeline answer (what the real pipeline would do). The rule layer alone is a first-pass heuristic that is expected to abstain (`UNSURE`) on plenty of cases and defer to Qwen -- that abstention is not a combined-pipeline error, and is not marked here; the rule layer's own alone-accuracy above already counts every abstention honestly.

## Every case

| id | category | expected | rule | qwen | combined | resolution | error? |
|---|---|---|---|---|---|---|---|
| en_delete_1 | delete-en | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_delete_2 | delete-en | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_delete_3 | delete-en | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_delete_4 | delete-en | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_delete_5 | delete-en | DELETE | DELETE | DELETE | DELETE | agreement |  |
| es_delete_1 | delete-es | DELETE | DELETE | DELETE | DELETE | agreement |  |
| es_delete_2 | delete-es | DELETE | DELETE | DELETE | DELETE | agreement |  |
| fr_delete_1 | delete-fr | DELETE | DELETE | DELETE | DELETE | agreement |  |
| pt_delete_1 | delete-pt | DELETE | DELETE | DELETE | DELETE | agreement |  |
| ja_delete_1 | delete-ja | DELETE | DELETE | DELETE | DELETE | agreement |  |
| ko_delete_1 | delete-ko | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_access_1 | access | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_correction_1 | correction | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_login_1 | login | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_invoice_1 | invoice | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_marketing_1 | marketing | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_email_change_1 | email-change | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_update_1 | update | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_negation_1 | negation-en | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_negation_2 | negation-en | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_negation_3 | negation-en | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| es_negation_1 | negation-es | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| fr_negation_1 | negation-fr | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| pt_negation_1 | negation-pt | NOT_DELETE | DELETE | NOT_DELETE | NOT_DELETE | unresolved_default |  |
| ja_negation_1 | negation-ja | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| ko_negation_1 | negation-ko | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_limit_1 | limit | NOT_DELETE | NOT_DELETE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_limit_2 | limit | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| es_limit_1 | limit | NOT_DELETE | DELETE | NOT_DELETE | NOT_DELETE | unresolved_default |  |
| mixed_1 | mixed | DELETE | DELETE | DELETE | DELETE | agreement |  |
| mixed_2 | mixed | NOT_DELETE | DELETE | NOT_DELETE | NOT_DELETE | unresolved_default |  |
| en_indirect_1 | indirect | DELETE | UNSURE | DELETE | DELETE | agreement |  |
| en_indirect_2 | indirect | DELETE | UNSURE | DELETE | DELETE | agreement |  |
| en_indirect_3 | indirect | DELETE | UNSURE | DELETE | DELETE | agreement |  |
| en_indirect_4 | indirect | NOT_DELETE | UNSURE | NOT_DELETE | NOT_DELETE | agreement |  |
| en_verify_1 | verify | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_verify_2 | verify | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_verify_3 | verify | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_inject_1 | injection | NOT_DELETE | NOT_DELETE | UNCLEAR | NOT_DELETE | unresolved_default |  |
| en_inject_2 | injection | NOT_DELETE | DELETE | UNCLEAR | NOT_DELETE | unresolved_default |  |
| es_inject_1 | injection | NOT_DELETE | NOT_DELETE | UNCLEAR | NOT_DELETE | unresolved_default |  |
| en_inject_3 | injection | DELETE | DELETE | DELETE | DELETE | agreement |  |
| en_unclear_1 | ambiguous | UNCLEAR | UNSURE | UNCLEAR | NOT_DELETE | unresolved_default |  |
| en_unclear_2 | ambiguous | UNCLEAR | UNSURE | UNCLEAR | NOT_DELETE | unresolved_default |  |

## Combined-pipeline errors in detail

No combined-pipeline error on any non-ambiguous case.

