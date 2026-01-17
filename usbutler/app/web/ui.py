"""UI router for HTML endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.reader_control import ReaderControl
from app.web.common import (
    _TEMPLATES_DIR,
    _is_web_reader_enabled,
    AuthService,
    ReaderStateOut,
    UserOut,
    get_auth_service,
    get_reader_control,
)

router = APIRouter()
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    reader_control_dep: ReaderControl = Depends(get_reader_control),
) -> HTMLResponse:
    users = auth_service.list_users()
    serialized = [UserOut.model_validate(user, from_attributes=True) for user in users]
    serialized.sort(key=lambda item: item.name.lower())
    owner = str(reader_control_dep.get_owner() or "door")
    reader_state = ReaderStateOut(
        owner=owner,
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "users": serialized,
            "reader_enabled": _is_web_reader_enabled(),
            "reader_state": reader_state.model_dump(),
        },
    )
