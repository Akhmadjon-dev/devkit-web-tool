from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.notes import NotesStore
from app.core.text import query_terms

_MAX_SNIPPET = 200


async def search_code(repo_path: Path, query: str, *, top_k: int = 6) -> list[dict]:
    """Non-LLM keyword search over the repo via `git grep` - cheap, read-only,
    safe on the hot path. git is already a hard dependency of this whole tool
    (unlike ripgrep, which isn't guaranteed to be installed), and `git grep`
    already respects .gitignore and covers tracked + untracked files.
    """
    terms = query_terms(query)
    if not terms:
        return []

    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        proc = await asyncio.create_subprocess_exec(
            "git", "grep", "-n", "-i", "--untracked", "-I", "-e", term,
            cwd=str(repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode not in (0, 1):  # 1 = no matches, not an error
            continue
        for line in stdout.decode(errors="replace").splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            file, lineno, content = parts
            key = (file, lineno)
            if key in seen:
                continue
            seen.add(key)
            results.append({"file": file, "line": int(lineno), "snippet": content.strip()[:_MAX_SNIPPET]})
            if len(results) >= top_k:
                return results
    return results


def format_context(*, notes: list[dict], code_hits: list[dict]) -> str:
    if not notes and not code_hits:
        return ""
    parts: list[str] = []
    if notes:
        lines = "\n".join(f"- [{n['kind'] or 'note'}] {n['text']}" for n in notes)
        parts.append(f"Relevant project notes/conventions (follow these):\n{lines}")
    if code_hits:
        lines = "\n".join(f"- {h['file']}:{h['line']}: {h['snippet']}" for h in code_hits)
        parts.append(f"Relevant existing code (grep hits, not exhaustive - look further if needed):\n{lines}")
    return "\n\n".join(parts)


async def build_context(repo_path: Path, notes_store: NotesStore, query: str, *, top_k: int = 5) -> str:
    code_hits = await search_code(repo_path, query, top_k=top_k)
    note_hits = notes_store.search(query, top_k=top_k)
    return format_context(notes=note_hits, code_hits=code_hits)
