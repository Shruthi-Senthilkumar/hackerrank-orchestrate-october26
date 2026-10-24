# Logging instructions for the Claude terminal

These rules add to `AGENTS.md` sections 2, 5 and 9. If anything here ever conflicts with `AGENTS.md`, `AGENTS.md` wins.
The goal is a `log.txt` that is valid for the chat-transcript submission and that also shows the terminal work.

## Every turn

1. Respond to the user's message and do the work.
2. **Before your final answer**, append exactly one entry to `log.txt` in the repo root, in the `AGENTS.md` section 5.2 format.
3. Run `python claude_terminal/log_tools.py check`. If it fails, fix **your own entry from this turn** and run it again. Never edit or reorder earlier entries.
4. Only then give your final answer.

At the start of a session: pull (`git pull --rebase`), then append a `SESSION START` entry (section 5.1) and greet the user as `AGENTS.md` section 3 says.

## `tool=` and `model=`

- `tool=` is the harness that is writing the entry, for example `Claude Code`.
- `model=` is the exact model ID of the running session. Read it from the runtime (`/status`, `/model`, or the session metadata). Never guess it, shorten it to a family name, or reuse a name from a previous session without checking.
- If you cannot determine the model ID, stop and ask the user. Do not write `unknown`.

## Terminal activity goes in `Actions`

The user wants the log to show terminal work too. In the `Actions:` list of the entry:

- Record **every command you ran**: `* cmd: <command> -> <one-line result>` (exit status, pass/fail counts, files written).
- Record commands the user ran themselves with `!` or told you about as `* user cmd: <command> -> <result>`.
- Record every file you created or edited as `* wrote: <path>` or `* edited: <path>`.
- Record tool calls such as web search or API smoke tests as `* tool: <name> -> <result>`.
- Summarize long output. Never paste more than a few lines, and never paste a whole file or a binary.

## Never log secrets or personal data

- Replace any key, token, cookie, password or private key with `[REDACTED]`, in the prompt, the summary and the actions.
- Commands that use secrets are logged by variable name only, for example `GROQ_API_KEY` set, never its value.
- Do not Read or print `.env`. To check that a key exists, use a script that prints only `set` or `missing`.
- Dataset records are fictional, but still do not copy personal-looking values from evidence into the log. Reference file and record IDs instead.

## Write the entry safely on Windows

- Do **not** append with PowerShell `>>`, `Out-File` or `Add-Content` defaults: they can write UTF-16 or CRLF, which breaks the format.
- Append with Python so the file stays UTF-8 with LF line endings:

  ```python
  with open("log.txt", "a", encoding="utf-8", newline="\n") as f:
      f.write(entry_text)
  ```

- `entry_text` must start with a blank-line-separated `## <ISO-8601 UTC timestamp> <title up to 80 chars>` header and end with a blank line.

## Phase boundaries

When a phase's exit checks have been run, make the entry title `PHASE <n> complete: <result>` (still within 80 characters), and list the exit-check commands and their results in `Actions`.
When the user pastes a phase prompt, the entry's `User Prompt` is that prompt verbatim.

## Commits

- Commit `log.txt` together with the work it describes. Run `python claude_terminal/log_tools.py check` first.
- Before every commit, scan the staged diff for key patterns (`gsk_`, `AIza`, `sk-`, `api_key=`). If anything matches, unstage it and tell the user.
- Push only to the user's fork (`origin`). Never push to the organizers' repo.
