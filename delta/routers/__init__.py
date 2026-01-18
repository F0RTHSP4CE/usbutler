from .users import router as users_router
from .identifiers import router as identifiers_router
from .doors import router as doors_router
from .user_identifiers import router as user_identifiers_router

__all__ = [
    "users_router",
    "identifiers_router",
    "doors_router",
    "user_identifiers_router",
]
