"""RESTful API router - aggregates all route modules."""

from __future__ import annotations

from fastapi import APIRouter

from app.web.routes import (
    users_router,
    identifiers_router,
    doors_router,
    reader_router,
)

router = APIRouter()

# Include all route modules
router.include_router(users_router)
router.include_router(identifiers_router)
router.include_router(doors_router)
router.include_router(reader_router)
