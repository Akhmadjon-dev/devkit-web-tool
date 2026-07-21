from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.reconcile import reconcile_on_startup
from app.core.scheduler import SchedulerError
from app.core.worktrees import WorktreeError
from app.services import build_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("devworkspace")

OPEN_PATHS = {"/healthz"}
FRONTEND_DEV_PORT = 5173


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()
    token = settings.resolve_token()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = build_services(settings)
        await reconcile_on_startup(app.state.services)
        logger.info("devworkspace ready on %s:%s (repo=%s)", settings.host, settings.port, settings.repo_root)
        logger.info("open the app: http://localhost:%s/?token=%s", FRONTEND_DEV_PORT, token)
        yield

    app = FastAPI(title="DevWorkspace", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://localhost:{FRONTEND_DEV_PORT}", f"http://127.0.0.1:{FRONTEND_DEV_PORT}"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def local_token_auth(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in OPEN_PATHS:
            # CORS preflight requests never carry our Authorization header (and
            # carry no credentials at all) - let CORSMiddleware answer them.
            return await call_next(request)
        supplied = request.headers.get("authorization", "")
        supplied = supplied.removeprefix("Bearer ").strip()
        if not supplied:
            supplied = request.query_params.get("token", "")
        if supplied != token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(WorktreeError)
    async def worktree_error_handler(request: Request, exc: WorktreeError) -> JSONResponse:
        # Most common cause: base_branch doesn't exist in this repo (e.g. it
        # uses "master", not "main" - see DEVWORKSPACE_BASE_BRANCH).
        logger.warning("worktree error: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(SchedulerError)
    async def scheduler_error_handler(request: Request, exc: SchedulerError) -> JSONResponse:
        logger.warning("scheduler error: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    from app.api.rest import router as rest_router
    from app.api.ws import router as ws_router

    app.include_router(rest_router)
    app.include_router(ws_router)

    return app


app = create_app()
