from __future__ import annotations

import asyncio

import pytest

from app.core.task_registry import TaskRegistry


@pytest.mark.asyncio
async def test_cancel_session_cancels_tracked_tasks():
    registry = TaskRegistry()
    started = asyncio.Event()
    cancelled = False

    async def long_running():
        nonlocal cancelled
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = asyncio.create_task(long_running())
    registry.track("sess_1", task)
    await started.wait()

    await registry.cancel_session("sess_1")

    assert cancelled is True
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_session_is_a_noop_for_unknown_session():
    registry = TaskRegistry()
    await registry.cancel_session("no-such-session")  # must not raise


@pytest.mark.asyncio
async def test_done_task_is_pruned_from_registry():
    registry = TaskRegistry()

    async def quick():
        return 1

    task = asyncio.create_task(quick())
    registry.track("sess_2", task)
    await task
    await asyncio.sleep(0)  # let the done-callback run

    assert task not in registry._tasks.get("sess_2", set())
