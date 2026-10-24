"""FastAPI application factory and main entrypoint."""
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from app.config import get_settings
from app.logging_config import request_id_ctx, setup_logging
from app.services.storage import get_storage
from app.services.storage.local import LocalStorageDriver


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context."""
    settings = get_settings()
    setup_logging(debug=settings.DEBUG)
    # Ensure storage driver is initialized
    get_storage()
    # Start background WebSocket ping loop
    from app.services.websocket import broadcaster
    broadcaster.start_background_tasks()
    yield
    broadcaster.stop_background_tasks()


def create_app() -> FastAPI:
    """Builds and configures the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID and Timing Middleware
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_ctx.reset(token)

    # Mount API v1 Routers
    from app.api.v1.router import v1_router
    from app.api.ws import router as ws_router
    app.include_router(v1_router)
    app.include_router(ws_router)

    # Health check endpoints
    @app.get("/health", tags=["System"])
    @app.get(f"{settings.API_V1_PREFIX}/ping", tags=["System"])
    async def health_check():
        return {
            "status": "ok",
            "service": settings.PROJECT_NAME,
            "version": "0.1.0",
        }

    # Serve media files in local storage mode
    @app.api_route(f"{settings.API_V1_PREFIX}/media/{{file_path:path}}", methods=["GET", "HEAD"], tags=["Media"])
    async def get_local_media(file_path: str):
        storage = get_storage()
        if isinstance(storage, LocalStorageDriver):
            path = storage._resolve_path(file_path)
            if path.is_file():
                return FileResponse(path)

            # Check if requested as detection/{id}/{kind}
            if file_path.startswith("detection/"):
                parts = file_path.split("/")
                if len(parts) >= 3:
                    det_id, kind = parts[1], parts[2].split(".")[0]
                    det_dir = storage.base_path / "detections" / det_id
                    if det_dir.is_dir():
                        for candidate in det_dir.glob(f"{kind}*"):
                            if candidate.is_file():
                                return FileResponse(candidate)

            # Fallback check for sample captures during development
            sample_dir = Path(__file__).resolve().parent.parent / "gate_captures"
            if sample_dir.is_dir():
                for candidate in sample_dir.glob("*.jpg"):
                    if "plate" in file_path and "_1_plate" in candidate.name:
                        return FileResponse(candidate)
                    if "scene" in file_path and "_2_vehicle" in candidate.name:
                        return FileResponse(candidate)
                    if "load" in file_path and "_3_cargo" in candidate.name:
                        return FileResponse(candidate)

        return JSONResponse(status_code=404, content={"detail": "Media not found"})

    # Serve built React frontend SPA if dist exists
    from pathlib import Path
    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist_dir.is_dir():
        from starlette.staticfiles import StaticFiles

        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend_assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            if full_path.startswith(("api/", "ws/", "docs", "redoc", "openapi.json", "health")):
                return JSONResponse(status_code=404, content={"detail": "Not found"})

            target = dist_dir / full_path
            if full_path and target.is_file():
                return FileResponse(target)

            index_file = dist_dir / "index.html"
            if index_file.is_file():
                return FileResponse(index_file)
            return JSONResponse(status_code=404, content={"detail": "Frontend index not found"})

    return app


app = create_app()
