import csv
import io
import json
import sqlite3
from typing import Optional


def log_event(conn: sqlite3.Connection, event_type: str, detail: str, rule_name: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO audit_log (event_type, rule_name, detail) VALUES (?, ?, ?)",
        (event_type, rule_name, detail),
    )
    conn.commit()


def read_audit_log(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT seq, event_type, rule_name, detail FROM audit_log ORDER BY seq").fetchall()
    return [{"seq": r[0], "event_type": r[1], "rule_name": r[2], "detail": r[3]} for r in rows]


def export_audit_log(conn: sqlite3.Connection, as_format: str = "json") -> str:
    records = read_audit_log(conn)
    if as_format == "json":
        return json.dumps(records, indent=2)
    if as_format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["seq", "event_type", "rule_name", "detail"])
        writer.writeheader()
        writer.writerows(records)
        return buf.getvalue()
    raise ValueError(f"unsupported format: {as_format}")
