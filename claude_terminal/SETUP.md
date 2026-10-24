# Claude terminal setup (Windows 11 first, macOS/Linux notes inline)

This is the one-time setup for the Claude Code terminal that builds the solution on **your machine**, where your API keys live.
The web chat is for planning, review, doubts and interview prep. The terminal builds and runs the code.

## 1. Prerequisites

- Git, and Python 3.11 (`python --version` should print 3.11.x).
- Claude Code installed and signed in. Follow Anthropic's official install guide: https://docs.claude.com
- Your two API keys created: Groq (console.groq.com) and Google AI Studio (aistudio.google.com).

## 2. Clone your fork and open a PowerShell in the repo root

```powershell
git clone https://github.com/Shruthi-Senthilkumar/hackerrank-orchestrate-october26.git
cd hackerrank-orchestrate-october26
git pull --rebase
```

`log.txt`, `PRD.md`, `.gitignore`, `.env.example` and `claude_terminal/` are already in the repo.

## 3. Put your keys in `.env` (locally, never in any chat)

```powershell
copy .env.example .env
notepad .env
```

Fill in `GROQ_API_KEY=` and `GEMINI_API_KEY=`, save as UTF-8, and close Notepad. Then confirm git will never see it:

```powershell
git check-ignore -v .env
```

That must print a line naming `.gitignore`. If it prints nothing, stop and fix `.gitignore` before going further.
Never paste a key into Claude, into `log.txt`, or into a commit message. If a key ever leaks, delete it in the provider console and create a new one.

`.claude/settings.json` in the repo blocks Claude from reading `.env` with its file tool and the common `cat`/`type` commands. It is a guardrail, not a guarantee, so the rule above still stands.

## 4. Python environment (kept at the repo root, outside `code/`)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
```

If activation is blocked: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again.
macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate && export PYTHONUTF8=1`.

Packages are installed by the Phase 0 prompt, not by hand.

## 5. Start Claude Code from the repo root

```powershell
claude
```

It must be started from the repo root so it reads `CLAUDE.md` -> `AGENTS.md` and logs to the root `log.txt`.

Before pasting anything, find the exact model ID the session is using (for example with `/model` or `/status`) and keep it handy.
The logging rules forbid guessing it, and the agent must read it from the runtime.

## 6. Run a phase

1. Open `claude_terminal/phases/phase_N.md` for the current phase and paste the prompt block into Claude.
2. Let it work. Answer its `[CALIBRATE]` / `[VERIFY]` questions yourself.
3. When it reports, run these two checks yourself:

   ```powershell
   python claude_terminal/log_tools.py check
   git status
   ```

4. Paste the phase report into the web chat. We resolve every issue together, and only then do I release the next phase prompt.

## 7. One writer at a time for `log.txt`

`log.txt` is append-only and shared by every session. To avoid merge conflicts:

- Run `git pull --rebase` before starting the terminal, and `git push` when you stop.
- Don't have the web chat and the terminal both push log changes at the same moment.

## 8. Before you quit for the day or finish

- Exit Claude cleanly, run `/export` inside it, and keep the export.
- Session files live under `%USERPROFILE%\.claude\projects\`. `agent_trace_instructions.md` explains the optional `agent-trace.zip`. Check the HackerRank submission page for whether it is requested.
