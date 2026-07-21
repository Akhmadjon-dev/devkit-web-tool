from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.bus import bus
from app.config import get_settings

logger = logging.getLogger("devworkspace.ws")

router = APIRouter()

# HTTP auth runs as ASGI "http"-scoped middleware, which Starlette never
# invokes for "websocket"-scoped connections - so each socket checks the
# token itself on connect, from a query param since browsers can't set
# Authorization headers on WebSocket upgrade requests.


async def _authorized(ws: WebSocket) -> bool:
    token = get_settings().resolve_token()
    supplied = ws.query_params.get("token", "")
    if supplied != token:
        await ws.close(code=4401)
        return False
    return True


async def _pump(ws: WebSocket, topic: str) -> None:
    """Forward bus events to the socket until the client disconnects.

    We only ever send here (never receive), so Starlette's normal
    WebSocketDisconnect detection - which relies on receiving a disconnect
    message - doesn't fire. A closed client instead surfaces as a raw
    transport error out of send_json, which we treat the same way.
    """
    queue = bus.subscribe(topic)
    try:
        while True:
            event = await queue.get()
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                break
    except asyncio.CancelledError:
        raise
    finally:
        bus.unsubscribe(topic, queue)


@router.websocket("/ws/session/{session_id}")
async def ws_session(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    if not await _authorized(ws):
        return
    await _pump(ws, f"session:{session_id}")


@router.websocket("/ws/approvals")
async def ws_approvals(ws: WebSocket) -> None:
    await ws.accept()
    if not await _authorized(ws):
        return
    await _pump(ws, "approvals")


@router.websocket("/ws/cost")
async def ws_cost(ws: WebSocket) -> None:
    await ws.accept()
    if not await _authorized(ws):
        return
    await _pump(ws, "cost")


@router.websocket("/ws/worktrees")
async def ws_worktrees(ws: WebSocket) -> None:
    await ws.accept()
    if not await _authorized(ws):
        return
    await _pump(ws, "worktrees")
