from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services import build_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("devworkspace")

OPEN_PATHS = {"/healthz"}


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()
    token = settings.resolve_token()

    app = FastAPI(title="DevWorkspace", version="0.1.0")

    @app.middleware("http")
    async def local_token_auth(request: Request, call_next):
        if request.url.path in OPEN_PATHS:
            return await call_next(request)
        supplied = request.headers.get("authorization", "")
        supplied = supplied.removeprefix("Bearer ").strip()
        if not supplied:
            supplied = request.query_params.get("token", "")
        if supplied != token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.on_event("startup")
    async def on_startup() -> None:
        app.state.services = build_services(settings)
        logger.info("devworkspace ready on %s:%s (repo=%s)", settings.host, settings.port, settings.repo_root)
        logger.info("auth token (data_dir/token): %s", settings.token_file)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    from app.api.rest import router as rest_router

    app.include_router(rest_router)

    return app


app = create_app()
