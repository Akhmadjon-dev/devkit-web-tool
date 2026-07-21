from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/ping")
async def ping() -> dict:
    return {"pong": True}
