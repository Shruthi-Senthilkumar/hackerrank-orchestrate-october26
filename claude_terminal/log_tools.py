#!/usr/bin/env python3
"""Validate log.txt against the AGENTS.md section 5 format and scan it for secrets.

Usage (from the repo root, any OS):
    python claude_terminal/log_tools.py check            # checks ./log.txt
    python claude_terminal/log_tools.py check path/to/log.txt

Exit code 0 means every entry is valid and no secret pattern was found.
Standard library only. Never prints matched secret values, only line numbers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENTRY_RE = re.compile(r"^## \[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]? (.+)$")  # AGENTS.md 5.2 uses brackets; early entries do not
BAD_VALUES = {"", "unknown", "ai", "claude", "llm", "assistant", "n/a", "none"}
SECRET_PATTERNS = {
    "groq-style key": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "google-style key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "openai/anthropic-style key": re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    "key assignment": re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[=:]\s*[A-Za-z0-9_\-]{16,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def split_entries(lines: list[str]):
    entries, current = [], None
    for number, line in enumerate(lines, start=1):
        match = ENTRY_RE.match(line)
        if match:
            current = {"start": number, "ts": match.group(1), "title": match.group(2), "lines": []}
            entries.append(current)
        elif current is not None:
            current["lines"].append((number, line))
    return entries


def field_values(entry, key: str):
    prefix = key + "="
    return [text[len(prefix):].strip() for _, text in entry["lines"] if text.startswith(prefix)]


def check(path: Path) -> int:
    if not path.exists():
        print(f"FAIL: {path} does not exist")
        return 1
    raw = path.read_bytes()
    problems: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("file has a UTF-8 BOM")
    if b"\r\n" in raw:
        problems.append("file contains CRLF line endings (AGENTS.md requires LF)")
    if b"\x00" in raw:
        problems.append("file contains NUL bytes (probably UTF-16 from PowerShell redirection)")
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    entries = split_entries(lines)
    if not entries:
        problems.append("no '## <ISO timestamp> <title>' entries found")
    elif "SESSION START" not in entries[0]["title"]:
        problems.append("first entry is not a SESSION START entry")

    previous_ts = ""
    for entry in entries:
        where = f"entry at line {entry['start']} ({entry['title'][:40]})"
        if len(entry["title"]) > 80:
            problems.append(f"{where}: title longer than 80 characters")
        if entry["ts"] < previous_ts:
            problems.append(f"{where}: timestamp goes backwards")
        previous_ts = entry["ts"]
        for key in ("tool", "model"):
            values = field_values(entry, key)
            if len(values) != 1:
                problems.append(f"{where}: expected exactly one '{key}=' line, found {len(values)}")
            elif values[0].lower() in BAD_VALUES or "<" in values[0] or "[" in values[0]:
                problems.append(f"{where}: '{key}=' value is blank, generic or a placeholder")
        body = "\n".join(t for _, t in entry["lines"])
        if "SESSION START" in entry["title"]:
            for needed in ("Repo Root:", "Branch:", "Worktree:", "Parent Agent:", "Language:", "Time Remaining:"):
                if needed not in body:
                    problems.append(f"{where}: SESSION START is missing '{needed}'")
        else:
            for needed in ("User Prompt (verbatim, secrets redacted):", "Agent Response Summary:", "Actions:", "Context:"):
                if needed not in body:
                    problems.append(f"{where}: missing section '{needed}'")

    for number, line in enumerate(lines, start=1):
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                problems.append(f"line {number}: possible secret ({label}); value not shown")

    print(f"entries: {len(entries)}  lines: {len(lines)}")
    if problems:
        print("FAIL")
        for problem in problems:
            print(" -", problem)
        return 1
    print("OK: every entry has exactly one populated tool= and model= line, no secret patterns found")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "check":
        target = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent / "log.txt"
        return check(target)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
