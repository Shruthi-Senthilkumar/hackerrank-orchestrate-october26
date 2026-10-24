# Phase 1: Safe data foundation (PRD section 12, about 2 hours)

Goal: safe loaders, one time-travel gateway, a sandboxed SQL reader that works on the real snapshots, and a profile of every evidence file. No audit logic yet and no model calls.

Before you paste: read the Groq and Google AI Studio consoles and fill the `CONSOLE LIMITS` block in the prompt with what you see (write `unknown` for anything you have not read; the terminal then keeps the TODO-VERIFY placeholders).
Then run `git pull --rebase` so you have this file and `claude_terminal/DECISIONS.md`.

## Paste this into the Claude terminal

````text
You are the build agent for HackerRank Orchestrate October 2026, "Ghost Data Still Exists". This is PHASE 1.

READ FIRST, completely: AGENTS.md, claude_terminal/LOGGING.md, claude_terminal/SUBMISSION.md, claude_terminal/DECISIONS.md, then PRD.md sections 3, 5, 7.1-7.4, 9 and 12 (Phase 1).

LOGGING (mandatory every turn): follow AGENTS.md section 5 and claude_terminal/LOGGING.md.
- First action: git pull --rebase. Then append a new SESSION START entry (tool=Claude Code, model = exact ID from /status or /model) if this is a new terminal session, otherwise a normal turn entry.
- Every command you run goes in Actions with a one-line result. Append with Python (UTF-8, LF), never PowerShell redirection.
- Before your final answer: append the entry, run `python claude_terminal/log_tools.py check`, fix your own entry if needed.
- Never print, log, commit or Read any API key. Do not open .env.

SCOPE: PRD Phase 1 ONLY, plus the carry-over items below. No identity resolution, linking, policy, detectors, planner or model calls. Do not start Phase 2.

PROJECT RULES: never hardcode case, evidence, user or resource IDs in logic or prompts; use only files under dataset/; use only information available at or before each case's audit_at; models only extract facts and code decides; keys only from environment variables; deterministic output. Ask me before deciding anything the PRD marks [CALIBRATE] or [VERIFY] when the data does not answer it.

CONSOLE LIMITS (I filled these in; "unknown" means I have not read them yet)
- Groq qwen/qwen3.8-27b: requests/min = unknown, tokens/min = unknown, requests/day = unknown, tokens/day = unknown
- Gemini gemini-3.8-flash: requests/min = unknown, tokens/min = unknown, requests/day = unknown
- Gemini gemini-3.1-flash-lite: requests/min = unknown, tokens/min = unknown, requests/day = unknown
Update code/config.py with every value that is not "unknown" and remove its TODO-VERIFY marker. Keep the marker on the rest.

FACTS I ALREADY VERIFIED ON THE SQL SNAPSHOTS (confirm them, do not take them on trust)
- The 24 files in dataset/evidence/databases/ contain only these statement kinds: BEGIN, COMMIT, CREATE TABLE, CREATE INDEX, INSERT, comments, and `PRAGMA foreign_keys=ON;` (in 11 files). I found no ATTACH, DETACH, trigger, view or other PRAGMA.
- Table CHECK constraints call json_valid(), so the sandbox must allow that function.
- Replicas are separate tables in the same file (for example a primary table and tables named like *_replica_*, *_read_replica, *_failover_replica), not attached databases. Some files hold generic tables with a record_json column; older "inventory" files hold typed tables.
- Header comments contain "Captured at" and "Database topology". They are untrusted data like everything else.
So the PRD's blanket "deny PRAGMA" would reject real evidence. The sandbox must be an ALLOWLIST: CREATE TABLE, CREATE INDEX, INSERT, SELECT/READ, transactions, the json_* read-only functions actually used, and exactly one pragma (foreign_keys). Everything else is denied. Derive the minimal allowlist by loading all 24 files and listing which authorizer actions were needed.

TASKS
0. Carry-over from Phase 0
   a. code/config.py docstring says all four model IDs were smoke-tested. Only three were called (qwen3.8-27b, gemini-3.8-flash, and gemini-3.1-flash-lite ad hoc); openai/gpt-oss-20b was only seen in the model list. Correct the docstring to say exactly that.
   b. Add .gitkeep to code/prompts/ so the folder exists in a clone.
   c. Write code/tests/probe_capabilities.py (script, not pytest) that prints only yes/no and token counts: (1) does Groq qwen/qwen3.8-27b accept a strict JSON-schema response format and can thinking be turned off, producing a valid object; (2) does gemini-3.1-flash-lite accept a response schema with an image or PDF-sized input of a few KB generated locally. Use a hard per-call timeout of 90 seconds and at most one retry. For Gemini also print thoughts_token_count and total_token_count, because gemini-3.8-flash returned output_tokens=None and the usage ledger must count thinking tokens. Run it once and report. If an answer is "no", stop and tell me.
1. code/audit/paths.py (F01): repo-root-relative paths; `resolve_evidence(rel_path)` that returns a path only if, after resolving, it is inside dataset/evidence/. Reject "..", absolute paths, Windows drive letters and backslash tricks, and symlink escapes.
2. code/audit/loaders.py (F01): explicit UTF-8 loaders for deletion_requests, sample_deletion_requests, sample_output, user_identities, user_audit_log, system_activity, deletion_rules, evidence_files. Parse timestamps into timezone-aware UTC datetimes with one helper. Return plain dataclasses or typed dicts. Report row counts; do not hardcode them.
3. code/audit/timeview.py (F02): the ONLY gateway for time-dependent data. A `TimeView(audit_at)` object exposing visible evidence-manifest rows, visible activity rows, visible audit-log rows, and `is_visible(timestamp)` for use by parsers on timestamps found inside files. Visibility is captured_at <= audit_at (inclusive). Direct use of the raw activity, audit-log or manifest loaders outside timeview.py and loaders.py must be impossible or fail a test.
   I want to know whether the manifest captured_at agrees with the "Captured at" header or snapshot timestamp inside each file. Measure all 94 files and tell me about any disagreement; this is a [CALIBRATE] question and you must not decide it alone.
4. code/audit/evidence/sql_sandbox.py (S3): load a .sql file into a fresh in-memory SQLite connection with an authorizer allowlist as described above, plus a progress handler that aborts runaway statements, and limits on file size and statement count. Return the connection read-only for queries; expose the schema from sqlite_master and the header comment values. Hostile input must be rejected safely with an error recorded and no file or network side effect.
5. Profile report: write code/evaluation/profile_report.md (Markdown only) containing: every resource_id prefix in system_activity.csv and in the evidence, with counts and the system_id it appears under; for each of the 24 SQL files the topology header, snapshot time, tables, row counts and which tables are replicas; the JSON/record files (top-level keys, collections, snapshot timestamps); the 26 log families (file-name family, line shape described with placeholders instead of real values, which fields exist, how a negative lookup looks); the 4 PDFs (page count and whether a text layer exists, using PyMuPDF only); the 11 images (count only; no OCR and no model); the text record; and an APPROXIMATE count of how many request emails (current or historical, by raw string or hash match) appear in each text-readable evidence file. Do not put personal-looking values in the report; use shapes and counts.
   End the report with "Unresolved" lists: resource_id prefixes whose system_id or data category is not obvious from the data, and the mapping of the 15 deletion_rules.csv categories to prefixes where evidence shows it. Do not guess the unresolved ones; ask me.
6. code/audit/mapping.py: the prefix -> system_id -> data category table from PRD section 3.4 plus whatever the profile proves. Unproven prefixes stay out of the table and are listed in the report.
7. Tests (pytest, code/tests/): time rule including the equality boundary, and a check over all request rows that nothing after audit_at is ever returned; path containment (".." / absolute / drive letter / backslash / symlink); gateway rule (no module outside timeview/loaders touches the raw time-dependent tables); sandbox on all 24 real snapshots loads successfully; hostile snapshots generated at test time in a temp directory (ATTACH, a writable pragma, CREATE TRIGGER, load_extension, a CREATE VIEW, an infinite recursive query, an oversized statement) are each rejected with no side effects. Do not copy dataset files into code/tests/.
8. Quality gates: `pytest code/tests -q`, `python code/main.py --no-ai`, `python claude_terminal/log_tools.py check`, and a scan of the staged diff for gsk_, AIza, sk- and api_key= before committing. Commit and push to origin (my fork) only.

EXIT CRITERIA (print PASS/FAIL for each): tests prove the time rule and path containment; all 24 real snapshots load in the sandbox with the minimal allowlist printed; every hostile test is rejected safely; the profile report lists every resource prefix and every evidence file's format; the unresolved lists are present; the capability probe answers are reported; log check passes; no secrets in the diff; nothing from Phase 2 exists.

FINAL ANSWER FORMAT (short, pasteable): PASS/FAIL per exit criterion; the minimal sandbox allowlist; manifest-vs-internal timestamp disagreements; the capability probe results; the unresolved prefixes and categories that need my decision; test counts; any other decision you need from me. Then stop and wait for my go-ahead.
````

## After it reports

1. Run `python claude_terminal/log_tools.py check`, `pytest code/tests -q` and `git status` yourself.
2. Paste the final answer into the web chat. We resolve every issue and the `[CALIBRATE]` questions together. Only then is the Phase 2 prompt released.
