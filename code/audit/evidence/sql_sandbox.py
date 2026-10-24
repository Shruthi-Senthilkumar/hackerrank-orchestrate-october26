"""Sandboxed SQLite reader for the .sql evidence snapshots.

S3. Loads a .sql file into a fresh in-memory SQLite connection through an
authorizer ALLOWLIST (not the PRD's original blanket "deny PRAGMA" denylist,
which Phase 1 profiling showed would reject real evidence: 11 of the 24
files start with `PRAGMA foreign_keys=ON;`, and several use
`CHECK (json_valid(record_json))`). The allowlist below was derived
empirically by loading all 24 real snapshots under a logging authorizer and
recording every authorizer action SQLite actually requested (see
code/evaluation/profile_report.md). No ATTACH, DETACH, CREATE TRIGGER,
CREATE VIEW, CREATE VIRTUAL TABLE, or load_extension call was ever needed by
real evidence, so all of those are denied.

After loading, the connection is re-armed with a stricter, read-only
authorizer: only SELECT/READ and a small allowlist of scalar/aggregate
functions are permitted, so nothing (including the loader code's own
mistakes) can mutate evidence after capture.
"""

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 10_000_000
MAX_STATEMENTS = 5_000
LOAD_TIMEOUT_S = 10
QUERY_TIMEOUT_S = 5
PROGRESS_HANDLER_N_INSTRUCTIONS = 1000

# Functions actually required to load the real snapshots (CHECK constraints
# call json_valid()), plus a small fixed set of ordinary read-only
# aggregate/scalar functions needed to query them afterward. Anything else
# (including load_extension) is denied.
ALLOWED_FUNCTIONS = {
    "json_valid",
    "json_extract",
    "count",
    "max",
    "min",
    "sum",
    "avg",
    "length",
    "lower",
    "upper",
    "coalesce",
}

# The one pragma real evidence actually uses.
ALLOWED_PRAGMAS = {"foreign_keys"}


class SqlSandboxError(RuntimeError):
    """Raised when a .sql file is rejected by the sandbox (hostile or malformed)."""


def _count_statements(sql_text: str) -> int:
    """Count top-level ';'-terminated statements.

    Ignores ';' (and everything else) inside a single- or double-quoted
    string, a `-- ` line comment, or a `/* ... */` block comment, so a
    stray quote character inside a comment cannot desync the scan.
    """
    count = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and i + 1 < n and sql_text[i + 1] == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql_text[i + 1] == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and i + 1 < n and sql_text[i + 1] == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == ";":
            count += 1
        i += 1
    return count


def _make_load_authorizer(violations: list):
    def authorizer(action, arg1, arg2, dbname, source):
        if action in (
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_TRANSACTION,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_REINDEX,
        ):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA:
            if arg1 in ALLOWED_PRAGMAS:
                return sqlite3.SQLITE_OK
            violations.append(f"denied PRAGMA {arg1!r}")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            if arg2 in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            violations.append(f"denied function {arg2!r}")
            return sqlite3.SQLITE_DENY
        if action == 23:  # SQLITE_UPDATE: only the internal sqlite_master bookkeeping
            if arg1 == "sqlite_master":  # side effect of CREATE TABLE with PK/UNIQUE
                return sqlite3.SQLITE_OK
            violations.append(f"denied UPDATE on {arg1!r}")
            return sqlite3.SQLITE_DENY
        violations.append(f"denied action {action} ({arg1!r}, {arg2!r})")
        return sqlite3.SQLITE_DENY

    return authorizer


def _make_query_authorizer(violations: list):
    def authorizer(action, arg1, arg2, dbname, source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and arg2 in ALLOWED_FUNCTIONS:
            return sqlite3.SQLITE_OK
        violations.append(f"query-time denied action {action} ({arg1!r}, {arg2!r})")
        return sqlite3.SQLITE_DENY

    return authorizer


def _make_progress_handler(deadline: float):
    def handler():
        return 1 if time.monotonic() > deadline else 0

    return handler


HEADER_RE = re.compile(r"^--\s*([A-Za-z][A-Za-z0-9 _]*):\s*(.+?)\s*$")


def _parse_header_comments(sql_text: str) -> dict:
    header = {}
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--"):
            if stripped and not stripped.startswith("--"):
                break
            continue
        m = HEADER_RE.match(stripped)
        if m:
            header[m.group(1).strip()] = m.group(2).strip()
    return header


@dataclass
class SandboxedSnapshot:
    path: Path
    connection: sqlite3.Connection
    header: dict = field(default_factory=dict)

    def tables(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows if not r[0].startswith("sqlite_")]

    def row_count(self, table: str) -> int:
        return self.query(f'SELECT COUNT(*) FROM "{table}"')[0][0]

    def columns(self, table: str) -> list[str]:
        """Column names for `table`, via cursor.description (PRAGMA
        table_info is denied post-load, so this avoids needing it)."""
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        self.connection.set_progress_handler(
            _make_progress_handler(deadline), PROGRESS_HANDLER_N_INSTRUCTIONS
        )
        cur = self.connection.execute(f'SELECT * FROM "{table}" LIMIT 0')
        return [d[0] for d in cur.description]

    def rows_as_dicts(self, table: str) -> list[dict]:
        cols = self.columns(table)
        return [dict(zip(cols, row)) for row in self.query(f'SELECT * FROM "{table}"')]

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        self.connection.set_progress_handler(
            _make_progress_handler(deadline), PROGRESS_HANDLER_N_INSTRUCTIONS
        )
        try:
            return self.connection.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            raise SqlSandboxError(f"query rejected: {type(e).__name__}: {e}") from None

    def close(self) -> None:
        self.connection.close()


def load_sql_file(path: Path) -> SandboxedSnapshot:
    """Load a .sql evidence file into a fresh, sandboxed in-memory connection.

    Raises SqlSandboxError on any hostile or malformed input, with no file
    or network side effect. The returned connection accepts only SELECT and
    the allowed read-only functions; any further attempt to mutate data or
    run a denied statement raises SqlSandboxError.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as e:
        raise SqlSandboxError(f"cannot stat {path}: {e}") from None
    if size > MAX_FILE_BYTES:
        raise SqlSandboxError(f"{path} is {size} bytes, over the {MAX_FILE_BYTES} limit")

    sql_text = path.read_text(encoding="utf-8")
    n_statements = _count_statements(sql_text)
    if n_statements > MAX_STATEMENTS:
        raise SqlSandboxError(
            f"{path} has {n_statements} statements, over the {MAX_STATEMENTS} limit"
        )

    header = _parse_header_comments(sql_text)

    conn = sqlite3.connect(":memory:")
    violations: list[str] = []
    conn.set_authorizer(_make_load_authorizer(violations))
    deadline = time.monotonic() + LOAD_TIMEOUT_S
    conn.set_progress_handler(_make_progress_handler(deadline), PROGRESS_HANDLER_N_INSTRUCTIONS)

    try:
        conn.executescript(sql_text)
    except sqlite3.Error as e:
        conn.close()
        detail = f"; violations={violations[:5]}" if violations else ""
        raise SqlSandboxError(f"rejected while loading {path}: {type(e).__name__}: {e}{detail}") from None

    # Re-arm with the strict, read-only query authorizer before handing the
    # connection back; nothing after this point may mutate evidence.
    query_violations: list[str] = []
    conn.set_authorizer(_make_query_authorizer(query_violations))

    return SandboxedSnapshot(path=path, connection=conn, header=header)
