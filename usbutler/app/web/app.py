"""FastAPI app wiring for web UI and API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.services.reader_control import ReaderControl
from app.web.api import router as api_router
from app.web.common import (
    _STATIC_DIR,
    reset_services as _reset_services,
    set_reader_control,
)
from app.web.ui import router as ui_router


def reset_services(user_db_path: str | None = None) -> None:
    _reset_services(user_db_path)


def create_app(reader_control: ReaderControl | None = None) -> FastAPI:
    if reader_control is not None:
        set_reader_control(reader_control)
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    app.include_router(ui_router)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
