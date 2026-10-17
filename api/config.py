"""Explicit service configuration; no default credentials."""
from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    state_path: Path = Path("runtime/service.sqlite3")
    reader_token: str = field(default="", repr=False)
    admin_token: str = field(default="", repr=False)
    decision_limit: int = 500
    max_body_bytes: int = 65536
    max_parallel_jobs: int = 2

    def __post_init__(self):
        if not 1 <= self.decision_limit <= 100_000:
            raise ValueError("decision_limit must be between 1 and 100000")
        if any(token and len(token) < 32 for token in (self.reader_token, self.admin_token)):
            raise ValueError("configured service tokens must contain at least 32 characters")
        if self.reader_token and self.reader_token == self.admin_token:
            raise ValueError("reader and admin credentials must be different")
        if not 1 <= self.max_parallel_jobs <= 16:
            raise ValueError("max_parallel_jobs must be between 1 and 16")
        if not 1024 <= self.max_body_bytes <= 1_048_576:
            raise ValueError("max_body_bytes must be between 1024 and 1048576")

    @classmethod
    def from_env(cls):
        return cls(state_path=Path(os.getenv("FUSION_STATE_DB", "runtime/service.sqlite3")),
                   reader_token=os.getenv("FUSION_READER_TOKEN", ""),
                   admin_token=os.getenv("FUSION_ADMIN_TOKEN", ""))
