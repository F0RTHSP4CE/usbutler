"""FastAPI app wiring for web UI and API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.api import router as api_router
from app.web.common import _STATIC_DIR
from app.web.ui import router as ui_router


def create_app() -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    app.include_router(ui_router)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
