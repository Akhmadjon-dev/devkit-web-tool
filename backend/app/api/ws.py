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
    queue = bus.subscribe(topic)
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
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
