"""API Routers."""

from app.routers.users import router as users_router
from app.routers.doors import router as doors_router
from app.routers.identifiers import router as identifiers_router
from app.routers.ui import router as ui_router

__all__ = [
    "users_router",
    "doors_router",
    "identifiers_router",
    "ui_router",
]
