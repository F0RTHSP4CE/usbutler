"""UI router for HTML endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.reader_control import ReaderControl
from app.web.common import (
    _TEMPLATES_DIR,
    _is_web_reader_enabled,
    AuthenticationService,
    ReaderStateOut,
    ScanSummary,
    StatsOut,
    UserOut,
    get_auth_service,
    get_last_scan,
)

router = APIRouter()
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    auth_service: AuthenticationService = Depends(get_auth_service),
    reader_control_dep: ReaderControl = Depends(ReaderControl),
    last_scan: ScanSummary | None = Depends(get_last_scan),
) -> HTMLResponse:
    users = list(auth_service.list_users().values())
    serialized = [UserOut.model_validate(user, from_attributes=True) for user in users]
    serialized.sort(key=lambda item: item.name.lower())
    total = len(users)
    active = sum(1 for user in users if user.active)
    stats = StatsOut(total=total, active=active, inactive=total - active)
    reader_state_raw = reader_control_dep.get_state()
    owner = str(reader_state_raw.get("owner") or "door")
    updated_at = reader_state_raw.get("updated_at")
    reader_state = ReaderStateOut(
        owner=owner,
        owned_by_web=owner == "web",
        owned_by_door=owner == "door",
        updated_at=updated_at if isinstance(updated_at, (int, float)) else None,
    )
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
