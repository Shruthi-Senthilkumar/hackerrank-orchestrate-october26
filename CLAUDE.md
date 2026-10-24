@AGENTS.md

## Logging and terminal workflow

Follow `claude_terminal/LOGGING.md` for every turn (it adds to `AGENTS.md` section 5, which still wins on any conflict).
Build one PRD phase at a time using the prompts in `claude_terminal/phases/`, and stop for the user at the end of each phase.
Never read, print or log `.env` or any API key.
