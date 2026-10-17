"""Transactional state for workers on one host using a shared SQLite file.

One policy revision is pinned per mission. Compare-and-swap updates prevent
lost writes; policy changes and their audit entries commit together. This is
not a multi-host consensus service and must not use a network filesystem.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .policy_engine import DEFAULT_POLICY_PATH, PolicyEngine, load_policy_text


class RevisionConflict(Exception):
    """A writer used a stale revision or reused a version for changed content."""


def canonical_policy(text: str) -> str:
    policy = load_policy_text(text)
    return json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class PolicySnapshot:
    revision: int
    text: str
    sha256: str
    updated_at: str

    def engine(self) -> PolicyEngine:
        if hashlib.sha256(self.text.encode()).hexdigest() != self.sha256:
            raise ValueError("stored policy checksum mismatch")
        return PolicyEngine.from_text(self.text)

    def public(self) -> dict:
        policy = self.engine()
        return {"revision": self.revision, "sha256": self.sha256,
                "updated_at": self.updated_at, "policy_id": policy.policy_id,
                "policy_version": policy.policy_version, "rule_count": policy.rule_count}


class ServiceState:
    def __init__(self, path: Path, decision_limit: int = 500):
        self.path = Path(path)
        self.decision_limit = decision_limit
        if not 1 <= decision_limit <= 100_000:
            raise ValueError("decision retention limit must be between 1 and 100000")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        # File permissions complement role checks; deployment still needs an
        # appropriately protected parent directory and encrypted storage.
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if schema_version not in (0, 1):
                raise ValueError("unsupported service-state schema version")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS policy_revisions (
                    revision INTEGER PRIMARY KEY, text TEXT NOT NULL,
                    sha256 TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policy_audit (
                    revision INTEGER PRIMARY KEY, prior_revision INTEGER,
                    actor_role TEXT NOT NULL, sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    conclusion_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            text = canonical_policy(DEFAULT_POLICY_PATH.read_text())
            digest = hashlib.sha256(text.encode()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM policy_revisions LIMIT 1").fetchone() is None:
                conn.execute("INSERT INTO policy_revisions VALUES (1, ?, ?, ?)", (text, digest, now))
                conn.execute("INSERT INTO policy_audit VALUES (1, NULL, 'initialization', ?, ?)", (digest, now))
            conn.commit()
        self.path.chmod(0o600)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    @staticmethod
    def _snapshot(row) -> PolicySnapshot:
        if row is None:
            raise ValueError("active policy is missing")
        return PolicySnapshot(row["revision"], row["text"], row["sha256"], row["updated_at"])

    def current_policy(self) -> PolicySnapshot:
        with self._connection() as conn:
            snapshot = self._snapshot(conn.execute(
                "SELECT * FROM policy_revisions ORDER BY revision DESC LIMIT 1").fetchone())
        snapshot.engine()  # Fail closed on invalid or corrupted persisted state.
        return snapshot

    def replace_policy(self, text: str, expected_revision: int) -> PolicySnapshot:
        text = canonical_policy(text)  # Validate before taking the write lock.
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._snapshot(conn.execute(
                "SELECT * FROM policy_revisions ORDER BY revision DESC LIMIT 1").fetchone())
            if current.revision != expected_revision:
                raise RevisionConflict("active revision changed; read the current policy before retrying")
            before = current.engine().policy
            after = load_policy_text(text)
            if before.policy_version == after.policy_version and current.sha256 != digest:
                raise RevisionConflict("changed policy content requires a new policy_version")
            if current.sha256 == digest:
                return current
            now = datetime.now(timezone.utc).isoformat()
            revision = current.revision + 1
            conn.execute("INSERT INTO policy_revisions VALUES (?, ?, ?, ?)", (revision, text, digest, now))
            conn.execute("INSERT INTO policy_audit VALUES (?, ?, 'admin', ?, ?)",
                         (revision, current.revision, digest, now))
            conn.commit()
        return PolicySnapshot(revision, text, digest, now)

    def policy_history(self, limit: int = 100) -> list[dict]:
        with self._connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM policy_audit ORDER BY revision DESC LIMIT ?", (limit,))]

    def remember_decision(self, conclusion_id: str, payload: dict) -> None:
        encoded = json.dumps(payload, allow_nan=False)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO decisions(conclusion_id, payload) VALUES (?, ?)", (conclusion_id, encoded))
            conn.execute("DELETE FROM decisions WHERE sequence NOT IN "
                         "(SELECT sequence FROM decisions ORDER BY sequence DESC LIMIT ?)", (self.decision_limit,))
            conn.commit()

    def decision(self, conclusion_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute("SELECT payload FROM decisions WHERE conclusion_id=?", (conclusion_id,)).fetchone()
        return json.loads(row[0]) if row else None
