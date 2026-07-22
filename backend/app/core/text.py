from __future__ import annotations

import re

_TERM = re.compile(r"\w+")


def query_terms(text: str, limit: int = 6) -> list[str]:
    """Cheap non-LLM keyword extraction shared by code search and notes FTS."""
    terms = [t for t in _TERM.findall(text.lower()) if len(t) > 2]
    seen: list[str] = []
    for t in terms:
        if t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen
