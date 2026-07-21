from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Override via env vars or a .env file in backend/."""

    model_config = SettingsConfigDict(env_prefix="DEVWORKSPACE_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8787

    # Repo this instance orchestrates work on. Must be a git repo.
    repo_root: Path = Path.cwd()

    # Where our own state (db, worktree pool, generated token) lives.
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    # Path/name of the Claude Code CLI binary.
    claude_bin: str = "claude"

    # Concurrency cap for running agents at once (Phase 3).
    max_agents: int = 3

    # Per-session budget cap in USD; None = unlimited (Phase 5).
    default_budget_usd: float | None = None

    # Explicit auth token. If unset, one is generated and persisted to data_dir/token on first boot.
    token: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "devworkspace.db"

    @property
    def worktrees_dir(self) -> Path:
        return self.data_dir / "worktrees"

    @property
    def token_file(self) -> Path:
        return self.data_dir / "token"

    def resolve_token(self) -> str:
        """Return the auth token, generating + persisting one on first run."""
        if self.token:
            return self.token
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.token_file.exists():
            return self.token_file.read_text().strip()
        generated = secrets.token_urlsafe(32)
        self.token_file.write_text(generated)
        self.token_file.chmod(0o600)
        return generated

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
