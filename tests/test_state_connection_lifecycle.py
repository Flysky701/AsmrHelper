"""SQLite operations release handles without relying on garbage collection."""

import sqlite3

import pytest

from src.app.persistence.state_store import SqliteStateStore


def test_reads_close_connections_immediately(tmp_path, monkeypatch):
    opened = []
    connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)  # Keep alive so GC cannot hide an unclosed handle.
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    for _ in range(3):
        assert store.load_terminal_tasks() == []
    assert len(opened) == 4
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    store.db_path.unlink()


def test_connection_commits_and_rolls_back_before_closing(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    with store._connect() as connection:
        connection.execute("CREATE TABLE lifecycle (value TEXT)")
        connection.execute("INSERT INTO lifecycle VALUES ('committed')")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    with pytest.raises(RuntimeError, match="abort"):
        with store._connect() as failed_connection:
            failed_connection.execute("INSERT INTO lifecycle VALUES ('rolled back')")
            raise RuntimeError("abort")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        failed_connection.execute("SELECT 1")
    with store._connect() as connection:
        assert [row[0] for row in connection.execute("SELECT value FROM lifecycle")] == ["committed"]
