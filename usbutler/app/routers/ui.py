"""UI router for web interface."""

import secrets
from typing import Optional

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.dependencies import ServicesDepNoAuth

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory="app/templates")


def _is_authenticated(api_key: Optional[str]) -> bool:
    """Check if the API key cookie is valid."""
    if not settings.API_PASSWORD:
        # No password configured, allow all
        return True
    if not api_key:
        return False
    return secrets.compare_digest(api_key, settings.API_PASSWORD)


def _require_auth(api_key: Optional[str]):
    """Check authentication and return redirect if not authenticated."""
    if not _is_authenticated(api_key):
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, api_key: Optional[str] = Cookie(None)):
    """Login page."""
    # If already authenticated, redirect to home
    if _is_authenticated(api_key):
        return RedirectResponse(url="/", status_code=302)

    # If no password is set, redirect to home
    if not settings.API_PASSWORD:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    password: str = Form(...),
):
    """Handle login form submission."""
    if not settings.API_PASSWORD:
        return RedirectResponse(url="/", status_code=302)

    if secrets.compare_digest(password, settings.API_PASSWORD):
        # Store the API password in a cookie for browser to use in API calls
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="api_key",
            value=password,
            httponly=False,  # JavaScript needs access to send in API requests
            samesite="lax",
            max_age=60 * 60 * 24 * 7,  # 1 week
        )
        return response

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password"},
    )


@router.get("/logout")
async def logout():
    """Log out and clear session."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("api_key")
    return response


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    s: ServicesDepNoAuth,
    api_key: Optional[str] = Cookie(None),
):
    """Main page - users and card scanning."""
    if redirect := _require_auth(api_key):
        return redirect

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
            "auth_enabled": bool(settings.API_PASSWORD),
        },
    )


@router.get("/doors", response_class=HTMLResponse)
async def doors_page(
    request: Request,
    s: ServicesDepNoAuth,
    api_key: Optional[str] = Cookie(None),
):
    """Doors management page."""
    if redirect := _require_auth(api_key):
        return redirect

    last_event = s.door_control.get_last_door_event()

    # Get recent door events for history (last 20)
    events, _ = s.door_events.get_history(page=1, page_size=20)
    history = []
    for event in events:
        door = s.doors.get_by_id(event.door_id)
        history.append(
            {
                "id": event.id,
                "door_name": door.name if door else f"Door #{event.door_id}",
                "event_type": event.event_type.value,
                "username": event.username,
                "timestamp": event.timestamp,
            }
        )

    return templates.TemplateResponse(
        "doors.html",
        {
            "request": request,
            "doors": s.doors.get_all(),
            "last_event": last_event,
            "history": history,
            "auth_enabled": bool(settings.API_PASSWORD),
        },
    )
