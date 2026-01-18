"""UI router for web interface."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import (
    CardReaderPollingDep,
    DoorServiceDep,
    IdentifierServiceDep,
    UserServiceDep,
)

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user_service: UserServiceDep,
    identifier_service: IdentifierServiceDep,
    card_reader_polling: CardReaderPollingDep,
):
    """Main page - users and card scanning."""
    users = user_service.get_all()

    # Get last scan info
    last_scan = None
    last_scan_identifier = None
    if card_reader_polling:
        last_scan = card_reader_polling.get_last_scan()
        if last_scan:
            last_scan_identifier = identifier_service.get_by_value(last_scan["value"])

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
async def doors_page(
    request: Request,
    door_service: DoorServiceDep,
):
    """Doors management page."""
    doors = door_service.get_all()

    return templates.TemplateResponse(
        "doors.html",
        {
            "request": request,
            "doors": doors,
        },
    )
