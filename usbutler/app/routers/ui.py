"""UI router for web interface."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import ServicesDep

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, s: ServicesDep):
    """Main page - users and card scanning."""
    users = s.users.get_all()

    last_scan = None
    last_scan_identifier = None
    if s.card_reader_polling:
        last_scan = s.card_reader_polling.get_last_scan()
        if last_scan:
            last_scan_identifier = s.identifiers.get_by_value(last_scan["value"])

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "users": users,
            "last_scan": last_scan,
            "last_scan_identifier": last_scan_identifier,
        },
    )


@router.get("/doors", response_class=HTMLResponse)
async def doors_page(request: Request, s: ServicesDep):
    """Doors management page."""
    return templates.TemplateResponse(
        "doors.html",
        {
            "request": request,
            "doors": s.doors.get_all(),
        },
    )
