"""UI router for web interface."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import identifiers as identifiers_router_module
from app.services.door_service import DoorService
from app.services.identifier_service import IdentifierService
from app.services.user_service import UserService

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    """Main page - users and card scanning."""
    user_service = UserService(db)
    identifier_service = IdentifierService(db)

    users = user_service.get_all()

    # Get last scan info - access the module variable dynamically
    last_scan = None
    last_scan_identifier = None
    polling = identifiers_router_module._card_reader_polling
    if polling:
        last_scan = polling.get_last_scan()
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
async def doors_page(request: Request, db: Session = Depends(get_db)):
    """Doors management page."""
    door_service = DoorService(db)
    doors = door_service.get_all()

    return templates.TemplateResponse(
        "doors.html",
        {
            "request": request,
            "doors": doors,
        },
    )
