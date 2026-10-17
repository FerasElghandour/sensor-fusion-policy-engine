import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    sensor_source TEXT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conclusions (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    rule_name TEXT,
    detail TEXT NOT NULL
);
"""


def get_connection(db_path: str = "fusion_compliance.db") -> sqlite3.Connection:
    """`db_path=':memory:'` gives every caller an isolated in-memory database —
    tests and one-off scenario runs use that so they never touch disk state."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn
