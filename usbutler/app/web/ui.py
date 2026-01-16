"""UI router for HTML endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web.common import (
    _TEMPLATES_DIR,
    _build_stats,
    _is_web_reader_enabled,
    _serialize_reader_state,
    _serialize_user,
    get_auth_service,
    get_last_scan,
    get_reader_control,
    ScanSummary,
    AuthenticationService,
    ReaderControl,
)

router = APIRouter()
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    auth_service: AuthenticationService = Depends(get_auth_service),
    reader_control_dep: ReaderControl = Depends(get_reader_control),
    last_scan: ScanSummary | None = Depends(get_last_scan),
) -> HTMLResponse:
    users = list(auth_service.list_users().values())
    serialized = [_serialize_user(user) for user in users]
    serialized.sort(key=lambda item: item.name.lower())
    stats = _build_stats(users)
    reader_state = _serialize_reader_state(reader_control_dep)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "users": serialized,
            "stats": stats,
            "last_scan": last_scan.model_dump() if last_scan else None,
            "reader_enabled": _is_web_reader_enabled(),
            "reader_state": reader_state.model_dump(),
        },
    )
