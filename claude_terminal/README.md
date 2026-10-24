# claude_terminal: how the terminal build is run

This folder is the working agreement between you, the web chat (review and guidance) and the Claude terminal (builder).
It is not part of the submission: `code.zip` contains only `README.md` and `code/`.

| File | What it is |
|---|---|
| `SETUP.md` | One-time terminal setup, keys, environment, how to run a phase |
| `LOGGING.md` | How the terminal keeps `log.txt` valid and includes terminal activity |
| `log_tools.py` | `python claude_terminal/log_tools.py check` validates `log.txt` and scans it for secrets |
| `phases/phase_N.md` | The prompt for each phase, released one at a time |

## Phase status

| Phase | PRD name | Prompt | Status |
|---|---|---|---|
| 0 | Setup | `phases/phase_0.md` | Released |
| 1 | Safe data foundation | not released | Locked until Phase 0 is complete and its issues are resolved |
| 2 | Identity and evidence | not released | Locked |
| 3 | Rules-only baseline | not released | Locked |
| 4 | Guarded AI layer | not released | Locked |
| 5 | Test and harden | not released | Locked |
| 6 | Ship | not released | Locked |
| 7 | Interview preparation | not released | Locked |

## The loop for every phase

1. Paste the phase prompt into the Claude terminal.
2. The terminal builds, runs the phase's exit checks and reports briefly.
3. You run `python claude_terminal/log_tools.py check` and `git status`.
4. You paste the report into the web chat. We resolve every issue.
5. The next phase prompt is released and added here.
