# Decisions and deviations log

One line per decision that departs from the PRD or settles a `[CALIBRATE]` / `[VERIFY]` item. This is the source for the "why" questions in the AI interview.
Add a row whenever a decision is made. Never delete rows; supersede them.

| # | Date (IST) | Decision | Why | Decided by | Status |
|---|---|---|---|---|---|
| D1 | 2026-10-24 | Intent model is `qwen/qwen3.8-27b`, not `qwen/qwen3-32b`. Fallback `openai/gpt-oss-20b`. | `qwen/qwen3-32b` and `qwen/qwen3.6-27b` are not in this Groq key's model list; `qwen/qwen3.8-27b` is the closest available. Confirmed by the user when the terminal asked. | User | Active. Structured-output and thinking-off support still to be probed (Phase 1 task 0c). |
| D2 | 2026-10-24 | Gemini readers are `gemini-3.8-flash` (primary) and `gemini-3.1-flash-lite` (second). | Both exist on the key. Flash took 142 s, 174 s and 313 s per call and once returned 503; Flash-Lite answered in 6.7 s. | User / terminal | Active. Revisit in Phase 4: hard per-call timeout, and possibly make Flash-Lite the primary reader. |
| D3 | 2026-10-24 | OCR engine is not chosen yet. PaddleOCR (PRD default) vs RapidOCR is decided at the start of Phase 4. | OCR is only needed for grounding image reads; installing it early adds risk and no value. | Plan | Open |
| D4 | 2026-10-24 | The SQL sandbox is an allowlist that permits CREATE TABLE, CREATE INDEX, INSERT, SELECT, transactions, json functions and exactly `PRAGMA foreign_keys`. The PRD's "deny PRAGMA" is relaxed to that one pragma. | The 24 snapshots really contain `PRAGMA foreign_keys=ON`, `CREATE INDEX` and `json_valid()` in CHECK constraints. A deny-all sandbox would reject real evidence. No ATTACH or trigger appears in the data. | Plan, from a grep of the dataset | Active. Phase 1 derives the minimal allowlist empirically. |
| D5 | 2026-10-24 | Replica drift is read from separate tables inside one snapshot file (primary vs `*_replica_*`, read, reporting and failover tables), not from attached databases. | Profile of the SQL files. | Plan | Active |
| D6 | 2026-10-24 | The usage ledger counts Gemini thinking tokens as output tokens. | `gemini-3.8-flash` returned `candidates_token_count=None` in the smoke test, so the visible count is unreliable. | Plan | Open until Phase 4 |
| D7 | 2026-10-24 | Do not submit an early draft to HackerRank. | The AI interview window opens at submission and lasts 12 hours. | Plan | Active until the platform confirms the resubmission rules |
| D8 | 2026-10-24 | `log.txt` is forced to LF with `.gitattributes`. | Windows `core.autocrlf` turned the log into CRLF and failed the format check. | Terminal | Active |
