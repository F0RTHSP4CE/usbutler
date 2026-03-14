"""UI router for web interface."""

import secrets
from typing import Optional
from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.dependencies import ServicesDepUI

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory="app/templates")


def _is_auth(api_key: Optional[str]) -> bool:
    if not settings.ADMIN_PASSWORD:
        return True
    return bool(
        api_key
        and secrets.compare_digest(
            api_key.encode("utf-8"), settings.ADMIN_PASSWORD.encode("utf-8")
        )
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, api_key: Optional[str] = Cookie(None)):
    if _is_auth(api_key) or not settings.ADMIN_PASSWORD:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if not settings.ADMIN_PASSWORD:
        return RedirectResponse(url="/", status_code=302)
    if secrets.compare_digest(
        password.encode("utf-8"), settings.ADMIN_PASSWORD.encode("utf-8")
    ):
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="api_key",
            value=password,
            httponly=False,
            samesite="lax",
            max_age=604800,
        )
        return response
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid password"}
    )


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("api_key")
    return response


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, s: ServicesDepUI,
):
    last_scan, last_scan_identifier = None, None
    if s.card_reader_polling:
        last_scan = s.card_reader_polling.get_last_scan()
        if last_scan:
            last_scan_identifier = s.identifiers.get_by_value(last_scan["value"])

    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "users": s.users.get_all(),
            "last_scan": last_scan,
            "last_scan_identifier": last_scan_identifier,
            "auth_enabled": bool(settings.ADMIN_PASSWORD),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/doors", response_class=HTMLResponse)
async def doors_page(
    request: Request, s: ServicesDepUI,
):
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
                "on_behalf_of": event.on_behalf_of,
                "timestamp": event.timestamp,
            }
        )

    response = templates.TemplateResponse(
        "doors.html",
        {
            "request": request,
            "doors": s.doors.get_all(),
            "last_event": s.door_control.get_last_door_event(),
            "history": history,
            "auth_enabled": bool(settings.ADMIN_PASSWORD),
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response
