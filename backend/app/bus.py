from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class Bus:
    """In-process pub/sub. Backend pushes events onto topics; the WS layer
    (Phase 2) subscribes and forwards to browser sockets. No external broker -
    this is a single-process app.
    """

    def __init__(self) -> None:
        self._topics: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._topics[topic].add(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        self._topics[topic].discard(q)
        if not self._topics[topic]:
            self._topics.pop(topic, None)

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        for q in list(self._topics.get(topic, ())):
            q.put_nowait(event)


bus = Bus()
