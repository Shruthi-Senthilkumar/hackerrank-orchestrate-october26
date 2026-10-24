import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

import pytest  # noqa: E402

from audit.evidence.sql_sandbox import (  # noqa: E402
    load_sql_file,
    SqlSandboxError,
    MAX_STATEMENTS,
    _count_statements,
)

REAL_SQL_DIR = REPO_ROOT / "dataset" / "evidence" / "databases"


def real_sql_files():
    return sorted(REAL_SQL_DIR.glob("*.sql"))


def test_all_24_real_snapshots_present():
    assert len(real_sql_files()) == 24


@pytest.mark.parametrize("path", real_sql_files(), ids=lambda p: p.name)
def test_each_real_snapshot_loads_successfully(path):
    snap = load_sql_file(path)
    tables = snap.tables()
    assert tables, f"{path} loaded with no tables"
    for t in tables:
        assert snap.row_count(t) >= 0
    snap.close()


def test_query_time_select_is_allowed_after_load():
    snap = load_sql_file(real_sql_files()[0])
    table = snap.tables()[0]
    rows = snap.query(f'SELECT * FROM "{table}" LIMIT 1')
    assert isinstance(rows, list)
    snap.close()


HOSTILE_CASES = {
    "attach": "ATTACH DATABASE 'evil.db' AS evil;",
    "writable_pragma": "PRAGMA journal_mode=WAL; CREATE TABLE t(x); INSERT INTO t VALUES(1);",
    "create_trigger": "CREATE TABLE t(x); CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END;",
    "load_extension": "SELECT load_extension('evil.dll');",
    "create_view": "CREATE TABLE t(x); CREATE VIEW v AS SELECT * FROM t;",
    "recursive_cte": (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
        "SELECT x FROM c LIMIT 1000000000;"
    ),
    "denied_function": "SELECT randomblob(10);",
}


@pytest.mark.parametrize("name,sql", HOSTILE_CASES.items(), ids=list(HOSTILE_CASES))
def test_hostile_statement_rejected_at_load(tmp_path, name, sql):
    path = tmp_path / f"{name}.sql"
    path.write_text(sql, encoding="utf-8")
    with pytest.raises(SqlSandboxError):
        load_sql_file(path)
    # no side effect: nothing written back to the hostile input file itself,
    # and no stray file created alongside it
    assert path.read_text(encoding="utf-8") == sql
    assert not (tmp_path / "evil.db").exists()


def test_statement_count_ignores_apostrophe_inside_line_comment():
    sql = "-- it's a hostile comment with an apostrophe\nCREATE TABLE t(x);\nINSERT INTO t VALUES(1);\n"
    assert _count_statements(sql) == 2


def test_statement_count_ignores_semicolon_and_quote_inside_block_comment():
    sql = (
        "/* this comment has a ; and an apostrophe ' inside it */\n"
        "CREATE TABLE t(x);\n"
        "INSERT INTO t VALUES('a;b');\n"
    )
    assert _count_statements(sql) == 2


def test_hostile_comment_with_apostrophe_does_not_desync_the_real_sandbox(tmp_path):
    sql = (
        "-- it's a hostile comment; ATTACH DATABASE 'evil.db' AS evil;\n"
        "CREATE TABLE t(x);\n"
        "INSERT INTO t VALUES(1);\n"
    )
    path = tmp_path / "hostile_comment.sql"
    path.write_text(sql, encoding="utf-8")
    snap = load_sql_file(path)
    assert snap.tables() == ["t"]
    assert snap.row_count("t") == 1
    snap.close()


def test_oversized_statement_count_rejected(tmp_path):
    sql = "CREATE TABLE t(x);" + " INSERT INTO t VALUES(1);" * (MAX_STATEMENTS + 1)
    path = tmp_path / "oversized.sql"
    path.write_text(sql, encoding="utf-8")
    with pytest.raises(SqlSandboxError):
        load_sql_file(path)


def test_oversized_file_bytes_rejected(tmp_path, monkeypatch):
    import audit.evidence.sql_sandbox as sandbox

    monkeypatch.setattr(sandbox, "MAX_FILE_BYTES", 100)
    path = tmp_path / "big.sql"
    path.write_text("-- padding\n" + ("x" * 200), encoding="utf-8")
    with pytest.raises(SqlSandboxError):
        sandbox.load_sql_file(path)


def test_query_time_mutation_denied_after_clean_load(tmp_path):
    path = tmp_path / "clean.sql"
    path.write_text("CREATE TABLE t(x); INSERT INTO t VALUES(1);", encoding="utf-8")
    snap = load_sql_file(path)
    for mutation in ("UPDATE t SET x = 99", "DELETE FROM t", "DROP TABLE t", "ATTACH 'x.db' AS x"):
        with pytest.raises(SqlSandboxError):
            snap.query(mutation)
    rows = snap.query("SELECT x FROM t")
    assert rows == [(1,)]
    snap.close()


def test_nonexistent_file_rejected():
    with pytest.raises(SqlSandboxError):
        load_sql_file(Path("does_not_exist_anywhere.sql"))
