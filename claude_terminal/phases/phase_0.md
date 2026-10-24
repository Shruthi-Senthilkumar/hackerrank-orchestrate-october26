# Phase 0: Setup (PRD section 12, about 0.5 hour)

Goal: a clean, safe project skeleton, working provider smoke tests, and the `[VERIFY]` facts resolved against your live accounts.
Phase 1 does not start until we have reviewed this phase's report together in the web chat.

## Paste this into the Claude terminal

````text
You are the build agent for HackerRank Orchestrate October 2026, "Ghost Data Still Exists".

READ FIRST, completely and in this order: AGENTS.md, claude_terminal/LOGGING.md, claude_terminal/SUBMISSION.md, README.md, problem_statement.md, PRD.md.

LOGGING (mandatory every turn): follow AGENTS.md section 5 and claude_terminal/LOGGING.md.
- First action: git pull --rebase, then append a SESSION START entry to log.txt. tool=Claude Code. model = the exact model ID read from the runtime (/status or /model); never guess it.
- Every command you run goes into the Actions list of that turn's entry, with a one-line result.
- Before your final answer each turn: append the entry, then run `python claude_terminal/log_tools.py check` and fix your own entry if it fails.
- Never print, log, commit or Read any API key. Do not open .env. Check keys only with a script that prints "set" or "missing".

SCOPE: PRD Phase 0 ONLY. Do not start Phase 1. Do not write audit logic.

RULES THAT APPLY TO THE WHOLE PROJECT: never hardcode case, evidence, user or resource IDs; use only files under dataset/; use only information available at or before each case's audit_at; models only extract facts or return enums and code decides everything; no Claude models inside the pipeline; keys only from environment variables. Ask me before deciding anything the PRD marks [CALIBRATE] or [VERIFY] when the data does not answer it.

TASKS
1. Repo hygiene: confirm the working tree is clean, .gitignore covers .env, .venv, .cache and __pycache__, and `git check-ignore -v .env` matches. Confirm .env exists and that GROQ_API_KEY and GEMINI_API_KEY are each set and non-empty (script prints only "set"/"missing").
2. Environment: use the .venv at the repo root (Python 3.11; create it if missing). Install: groq, google-genai, pymupdf, pillow, python-dotenv, jsonschema, rapidfuzz, pytest. Do NOT install any OCR engine now; OCR is decided at the start of Phase 4. Write code/requirements.txt with the versions that actually installed.
3. Skeleton: build the folder tree in claude_terminal/SUBMISSION.md section 2 exactly (it is PRD section 11 plus code/tools/ and the git-ignored submission/ folder), with empty packages and no logic yet.
   Create code/evaluation/evaluation_report.md and code/evaluation/usage_report.md as placeholders whose first line is `STATUS: PLACEHOLDER - generated in Phase 6`, so the packager can refuse to ship them unfinished.
   Put nothing needed by the judge into .csv/.json/.jsonl/.sql/.log files inside code/. Prompts and reports are .md or .py only.
   Detail of the files:
   - code/main.py: argparse CLI with --cases and --no-ai flags that currently only prints the plan and exits 0.
   - code/config.py: non-secret settings only. Model IDs are constants that are filled in only after task 5. Per-provider rate limits, batch size, token caps and the cache directory (.cache/ at repo root) are conservative placeholders marked TODO-VERIFY.
   - code/audit/ (with __init__.py and the subpackages evidence/, llm/, security/), code/prompts/, code/evaluation/, code/tests/, code/tools/. Keep the existing empty code/evaluation/main.py.
   - README.md: replace nothing the organizers wrote that is still needed; add a clear "Setup and run" section for Windows and macOS/Linux covering venv, keys, running the pipeline, evaluation and tests. Mark the parts that do not work yet.
4. Provider smoke tests in code/tests/smoke_providers.py (a script, not a pytest test): one tiny Groq call and one tiny Gemini call using the model IDs found in task 5. Print only: provider, model ID, "ok" or the error class plus HTTP status, input tokens, output tokens, latency. Never print keys or response bodies.
5. Resolve the PRD [VERIFY] items:
   a. List the models my keys can actually use (each provider's list-models API). Print only the model IDs that belong to the families named in PRD section 10.2, and say which PRD IDs exist and which do not.
   b. If a PRD model ID does not exist, do NOT substitute silently. Stop and show me the candidates so I can choose.
   c. Tell me which free-tier limits (requests/minute, tokens/minute, requests/day, tokens/day) I must read myself in the Groq and Google AI Studio consoles, because an API call cannot tell you. Put conservative values in config.py until I confirm.
6. Quality gates: run `pytest code/tests` (it may collect nothing), `python code/main.py --no-ai`, and `python claude_terminal/log_tools.py check`.
7. Commit with a message that has no secrets. Before committing, scan the staged diff for the patterns gsk_, AIza, sk- and api_key=. Push to origin (my fork) only.

EXIT CRITERIA: `git status` never lists .env; both smoke tests print ok; every [VERIFY] model ID is confirmed or I have chosen a replacement; log.txt check passes; nothing past Phase 0 exists; the tree matches SUBMISSION.md section 2; submission/ is git-ignored.

FINAL ANSWER FORMAT (short, so I can paste it to my reviewer): a PASS/FAIL line for each exit criterion; the confirmed model IDs; the list of limits I must read in the consoles; token counts from the smoke tests; any decision you need from me. Then stop and wait for my go-ahead.
````

## After it reports

1. Run `python claude_terminal/log_tools.py check` and `git status` yourself.
2. Paste the final answer into the web chat. We resolve every issue first. Only then is the Phase 1 prompt released.
