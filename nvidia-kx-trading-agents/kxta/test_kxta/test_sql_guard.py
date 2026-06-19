# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the always-on SQL execution rail (pure stdlib, no network)."""

from kxta.sql_guard import SQL_GUARD_BLOCK_MESSAGE, validate_sql


def test_valid_select_passes():
    ok, reason = validate_sql('SELECT "date", "close" FROM daily_prices WHERE "sym" = \'NVDA\' LIMIT 10')
    assert ok is True
    assert reason == "ok"


def test_leading_whitespace_and_trailing_semicolon_pass():
    ok, _ = validate_sql("   \n  SELECT * FROM trades;  ")
    assert ok is True


def test_semicolon_chained_statements_rejected():
    ok, reason = validate_sql("SELECT * FROM trades; DROP TABLE trades")
    assert ok is False
    assert "multiple" in reason.lower()


def test_semicolon_inside_string_literal_passes():
    ok, _ = validate_sql("SELECT * FROM trades WHERE note = 'a;b'")
    assert ok is True


def test_insert_rejected():
    ok, reason = validate_sql("INSERT INTO trades VALUES (1, 2, 3)")
    assert ok is False


def test_drop_rejected():
    ok, reason = validate_sql("DROP TABLE trades")
    assert ok is False


def test_lowercase_keywords_rejected():
    ok, reason = validate_sql("select * from t where 1=1 union select 1; drop table t")
    assert ok is False
    ok, reason = validate_sql("select 1 into outfile '/tmp/x'")
    assert ok is False
    assert "outfile" in reason.lower()


def test_deny_keyword_embedded_in_select_rejected():
    for kw in ("UPDATE",
               "DELETE",
               "CREATE",
               "ALTER",
               "TRUNCATE",
               "GRANT",
               "REVOKE",
               "EXEC",
               "ATTACH",
               "PRAGMA",
               "MERGE",
               "REPLACE"):
        ok, reason = validate_sql(f"SELECT * FROM t WHERE {kw} x")
        assert ok is False, f"{kw} should be rejected"
        assert kw in reason


def test_keywords_inside_string_literals_pass():
    ok, reason = validate_sql("SELECT * FROM users WHERE name = 'drop table'")
    assert ok is True, reason
    ok, reason = validate_sql("SELECT * FROM news WHERE headline = 'CREATE; DELETE and UPDATE'")
    assert ok is True, reason


def test_escaped_quotes_in_literals_handled():
    ok, reason = validate_sql("SELECT * FROM t WHERE name = 'O''Brien DROP'")
    assert ok is True, reason


def test_unterminated_string_rejected():
    ok, reason = validate_sql("SELECT * FROM t WHERE sym = 'NVDA")
    assert ok is False
    assert "unterminated" in reason.lower()


def test_code_fenced_sql_unwrapped():
    ok, reason = validate_sql("```sql\nSELECT * FROM trades\n```")
    assert ok is True, reason
    ok, reason = validate_sql("```\nSELECT 1\n```")
    assert ok is True, reason
    # Fenced DDL is still DDL
    ok, _ = validate_sql("```sql\nDROP TABLE trades\n```")
    assert ok is False


def test_leading_comment_then_select_passes():
    ok, reason = validate_sql("-- top movers\nSELECT * FROM trades")
    assert ok is True, reason
    ok, reason = validate_sql("/* generated */ SELECT 1")
    assert ok is True, reason


def test_non_select_start_rejected():
    ok, _ = validate_sql("SHOW TABLES")
    assert ok is False
    ok, _ = validate_sql("WITH x AS (SELECT 1) SELECT * FROM x")  # not SELECT-first by policy
    assert ok is False


def test_empty_rejected():
    for sql in ("", "   ", None, "```sql\n```"):
        ok, _ = validate_sql(sql)
        assert ok is False


def test_length_cap_default():
    long_sql = "SELECT * FROM t WHERE " + " AND ".join(f'"c{i}" = 1' for i in range(600))
    assert len(long_sql) > 4000
    ok, reason = validate_sql(long_sql)
    assert ok is False
    assert "character limit" in reason


def test_length_cap_env_override(monkeypatch):
    monkeypatch.setenv("SQL_GUARD_MAX_LEN", "20")
    ok, reason = validate_sql("SELECT * FROM trades WHERE 1 = 1")
    assert ok is False
    assert "20" in reason
    monkeypatch.setenv("SQL_GUARD_MAX_LEN", "5000")
    ok, _ = validate_sql("SELECT * FROM trades WHERE 1 = 1")
    assert ok is True


def test_block_message_constant_is_user_facing():
    assert "blocked by the execution guard" in SQL_GUARD_BLOCK_MESSAGE
