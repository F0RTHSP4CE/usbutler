"""API route modules."""

from app.web.routes.users import router as users_router
from app.web.routes.identifiers import router as identifiers_router
from app.web.routes.doors import router as doors_router
from app.web.routes.reader import router as reader_router

__all__ = [
    "users_router",
    "identifiers_router",
    "doors_router",
    "reader_router",
]
