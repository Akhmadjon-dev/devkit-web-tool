from __future__ import annotations

import asyncio
from collections import defaultdict


class TaskRegistry:
    """Tracks background asyncio Tasks (planner runs, run_all_tasks pipelines)
    by session id, so killing a session actually stops in-flight work instead
    of just relabeling it in the DB while a claude subprocess keeps running.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, set[asyncio.Task]] = defaultdict(set)

    def track(self, session_id: str, task: asyncio.Task) -> None:
        self._tasks[session_id].add(task)
        task.add_done_callback(lambda t: self._tasks[session_id].discard(t))

    async def cancel_session(self, session_id: str) -> None:
        tasks = list(self._tasks.get(session_id, ()))
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
