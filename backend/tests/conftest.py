from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.services import AppServices, build_services


async def _git(*args: str, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {err.decode()}")


@pytest.fixture
async def repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    await _git("init", "-q", "-b", "main", cwd=repo_path)
    await _git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init", cwd=repo_path)
    (repo_path / "README.md").write_text("hello\n")
    await _git("add", "README.md", cwd=repo_path)
    await _git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add readme", cwd=repo_path)
    return repo_path


@pytest.fixture
def services(tmp_path: Path, repo: Path) -> AppServices:
    settings = Settings(
        repo_root=repo,
        data_dir=tmp_path / "data",
        token="test-token",
    )
    return build_services(settings)
