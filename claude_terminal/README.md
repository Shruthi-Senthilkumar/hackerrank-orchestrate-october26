# claude_terminal: how the terminal build is run

This folder is the working agreement between you, the web chat (review and guidance) and the Claude terminal (builder).
It is not part of the submission: `code.zip` contains only `README.md` and `code/`.

| File | What it is |
|---|---|
| `SETUP.md` | One-time terminal setup, keys, environment, how to run a phase |
| `LOGGING.md` | How the terminal keeps `log.txt` valid and includes terminal activity |
| `SUBMISSION.md` | The three files to upload, the canonical folder tree, what goes in `code.zip`, preflight checks, and what to settle before submitting |
| `DECISIONS.md` | Every deviation from the PRD and every settled `[CALIBRATE]`/`[VERIFY]` item, with the reason (interview source) |
| `log_tools.py` | `python claude_terminal/log_tools.py check` validates `log.txt` and scans it for secrets |
| `phases/phase_N.md` | The prompt for each phase, released one at a time |

## Phase status

| Phase | PRD name | Prompt | Status |
|---|---|---|---|
| 0 | Setup | `phases/phase_0.md` | Done, passed with 3 carry-overs (folded into Phase 1 task 0) |
| 1 | Safe data foundation | `phases/phase_1.md` | Done. Reviewed and passed (61/61 tests also pass on Linux). |
| 2 | Identity and evidence | `phases/phase_2.md` | Built; review found a linker recall gap, fix-up phase 2b released |
| 2b | Linker recall fix-up | `phases/phase_2b.md` | Done. Reviewed and passed (97 tests). 12 unattributable pairs accepted as D17. |
| 3 | Rules-only baseline | `phases/phase_3.md` | Built (153 tests pass, 32/32 sample status). Review found over-linking; fix-up 3b released |
| 3b | Over-linking fix and calibration audit | `phases/phase_3b.md` | Done. Reviewed and passed (158 tests). |
| 4 | Guarded AI layer | `phases/phase_4.md` | Released |
| 5 | Test and harden | merged into `phases/phase_5_6.md` | Merged (deadline) |
| 6 | Ship | `phases/phase_5_6.md` | Combined prompt written; locked until Phase 4 is reviewed |
| 7 | Interview preparation | not released | Locked |

## The loop for every phase

1. Paste the phase prompt into the Claude terminal.
2. The terminal builds, runs the phase's exit checks and reports briefly.
3. You run `python claude_terminal/log_tools.py check` and `git status`.
4. You paste the report into the web chat. We resolve every issue.
5. The next phase prompt is released and added here.
