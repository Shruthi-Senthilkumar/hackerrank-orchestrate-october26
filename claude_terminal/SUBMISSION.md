# Submission: what to upload and how the repo is laid out

Sources used: the HackerRank challenge page (your screenshot), `README.md` (Packaging and Submission), `AGENTS.md` sections 6.8-6.9, `problem_statement.md`, `agent_trace_instructions.md`.
Where they differ, section 7 says which one we follow.

## 1. The three files you upload on HackerRank

| # | Upload | Where it comes from | Rules |
|---|---|---|---|
| 1 | **Code zip** (`code.zip`) | Built from `README.md` + the `code/` directory | Runnable solution, prompts, config, setup/run README, and both evaluation reports. Excludes virtual environments, `node_modules`, build artifacts, caches, the `dataset/` folder and any data corpus, and nested archives. |
| 2 | **Predictions CSV** (`output.csv`) | Written by `python code/main.py` at the repo root | Exact header `case_id,deletion_status,steps_json`, 518 data rows for `dataset/deletion_requests.csv`, sorted by `case_id`. |
| 3 | **Chat transcript** (`log.txt`) | The root `log.txt`, as the agent wrote it | Every entry follows `AGENTS.md` section 5 with populated `tool=` and `model=` lines. No secrets. |

Optional, only if the submission page asks for it: `agent-trace.zip`, staged as `agent_trace_instructions.md` describes (copies of your Claude Code session files, secrets removed). Check the page before assuming.

After a successful submission the AI Judge interview opens for 12 hours. It lasts 30 minutes, the camera must be on, and results are announced on 27 October 2026.

## 2. Canonical folder structure

```text
hackerrank-orchestrate-october26/            (repo root)
|-- README.md                  IN code.zip   setup + run for Windows and macOS/Linux, keys, evaluation, tests
|-- output.csv                 UPLOAD #2     generated, 518 rows, committed
|-- log.txt                    UPLOAD #3     append-only transcript
|-- AGENTS.md CLAUDE.md problem_statement.md PRD.md agent_trace_instructions.md    not zipped
|-- claude_terminal/           not zipped    our working docs, phase prompts, log checker
|-- dataset/                   NEVER zipped  provided data
|-- .env  .venv/  .cache/  submission/       git-ignored, never zipped
`-- code/                      IN code.zip
    |-- main.py                              entry: python code/main.py
    |-- config.py                            non-secret settings and model IDs
    |-- requirements.txt
    |-- prompts/                             Markdown prompts with a version string each
    |-- audit/                               paths, loaders, timeview, identity, linker, policy,
    |   |                                    detectors, decision, planner, validator, intent
    |   |-- evidence/  llm/  security/
    |-- evaluation/
    |   |-- main.py                          scorer and report generator
    |   |-- mutations.py  injection_tests.py
    |   |-- profile_report.md                Phase 1 profile of the data
    |   |-- evaluation_report.md             REQUIRED, Markdown only
    |   `-- usage_report.md                  REQUIRED, Markdown only
    |-- tests/                               pytest tests; fixtures generated at test time
    `-- tools/package_submission.py          builds the submission folder and runs the preflight checks
```

This is PRD section 11 plus two additions: `code/tools/` (packager) and the git-ignored `submission/` staging folder.

`submission/` holds exactly what you upload and nothing else:

```text
submission/
|-- code.zip
|-- output.csv
|-- log.txt
`-- agent-trace.zip      (only if the page asks for it)
```

## 3. What goes inside `code.zip`

Include: `README.md` (repo root) and everything under `code/`, including `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md`.

Exclude: `dataset/`, `.venv/`, `venv/`, `node_modules/`, `__pycache__/`, `.pytest_cache/`, `.cache/`, `.git/`, `.env`, `.DS_Store`, `output.csv`, `log.txt`, `claude_terminal/`, `PRD.md`, any `.zip/.tar/.gz/.tgz/.7z/.rar` inside it, and any copy of dataset records.

Must hold true:
- The two reports and all prompts are `.md` or `.py` files. The code judge ignores the content of `.csv`, `.tsv`, `.json`, `.jsonl`, `.sql` and `.log` files, so nothing the judge or interviewer needs may exist only in those formats.
- `evaluation_report.md` covers case-level status accuracy, step-level and field-level accuracy, sequence accuracy, at least three custom evaluation cases written by us, and failures found plus improvements made.
- `usage_report.md` covers the final full-dataset run that produced `output.csv`: providers and model names, model calls, input and output tokens, total and average tokens per request, estimated total and per-request cost, per-model and overall totals.
- No API keys, credentials, real personal data or sensitive configuration anywhere in the zip.
- Test fixtures are generated into a temporary folder at test time. Do not copy `dataset/` files into `code/tests/`.

## 4. Preflight checks (the packager runs all of these and refuses to continue on any failure)

1. `output.csv`: exact header, 518 rows, sorted, every `steps_json` is a JSON array with consecutive `step_no` from 1, phases in order, evidence IDs exist in the manifest or activity/audit logs and are not later than that case's `audit_at`, remediation and future verification steps have an empty `evidence_id`, `NOT_APPLICABLE` rows are `[]`. UTF-8, LF, no BOM.
2. Both evaluation reports exist, are not placeholders (no `STATUS: PLACEHOLDER` line), and contain the required sections.
3. `README.md` exists and has the setup and run instructions.
4. The zip has no forbidden paths or nested archives and contains the required files.
5. A secret scan of the zip contents, `log.txt` and the reports finds nothing.
6. `python claude_terminal/log_tools.py check` passes on `log.txt`.
7. A clean-checkout run reproduces `output.csv` byte for byte.

## 5. Order of the last steps

1. Final code is committed. Run the full pipeline once for the usage accounting. This writes `output.csv`.
2. Generate `evaluation_report.md` and `usage_report.md` from the real run. Commit.
3. Run `python code/tools/package_submission.py`. It builds `submission/code.zip` and runs the preflight checks.
4. Append the final `log.txt` entry for the submission turn, then run the log check.
5. Copy `output.csv` and the final `log.txt` into `submission/`. Copy the log last, because it must contain every turn.
6. Upload the three files (and `agent-trace.zip` only if requested).

## 6. Things to settle before you press submit

- **The interview window starts at submission.** The AI Judge interview opens after a successful submission and stays open 12 hours. Do not submit a draft just to have something in. Check on the platform whether you can resubmit, and whether the first or the last submission is graded. Until that is confirmed, submit once, when the solution is final and you can be on camera for 30 minutes. This overrides the PRD's idea of an early valid submission.
- **Deadline.** Not stated in the repo. Write down the start time of your 24 hours and the exact end time shown on the page.
- **The submission link in `AGENTS.md`** is spelled `wwww.hackerrank.com` (four w's). Use the link from the challenge page instead.
- **Size limits** for the three files are not stated. Check the upload form. The zip is small if `dataset/`, caches and environments are excluded.

## 7. Where the sources differ and what we follow

| Topic | Screenshot | README / AGENTS.md | We follow |
|---|---|---|---|
| Zip contents | "zip your code/ directory" | `README.md code` | `README.md` + `code/`, which is a superset of the screenshot, and the README is required inside the zip. |
| Report location | not stated | README: `code/evaluation/`. `AGENTS.md` and `problem_statement.md` say `evaluation/` | `code/evaluation/`, because the README marks it **Important** and it matches the starter layout. |
| Transcript | `log.txt` | root `log.txt`, `AGENTS.md` format | Root `log.txt`. |
| Agent trace | not mentioned | `agent_trace_instructions.md` asks for `agent-trace.zip` | Optional until the submission page says it is required. |
