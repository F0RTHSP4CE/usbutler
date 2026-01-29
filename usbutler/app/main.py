"""Main FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.dependencies import (
    set_card_reader_polling,
    get_door_control_service,
    create_services_for_thread,
)
from app.emv.nfc_reader import NFCReader
from app.routers import doors_router, identifiers_router, users_router, ui_router
from app.services.card_reader import CardReaderService
from app.services.card_reader_polling import CardReaderPollingService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Singletons
nfc_reader = NFCReader()
card_reader_service = CardReaderService(nfc_reader)
door_control_service = get_door_control_service()  # Use the singleton from dependencies
card_reader_polling: CardReaderPollingService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown."""
    global card_reader_polling

    # Startup
    logger.info("Starting usbutler...")

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Start button monitoring for all configured doors
    with create_services_for_thread() as services:
        doors = services.doors.get_all()
        if doors:
            door_control_service.start_button_monitoring(doors)
            logger.info(f"Button monitoring started for {len(doors)} doors")
        else:
            logger.info("No doors configured, button monitoring not started")

    # Start card reader polling
    card_reader_polling = CardReaderPollingService(
        card_reader_service=card_reader_service,
        door_control_service=door_control_service,
        poll_interval=settings.CARD_READER_POLL_INTERVAL,
        default_door_id=settings.DEFAULT_DOOR_ID,
    )
    set_card_reader_polling(card_reader_polling)
    card_reader_polling.start()
    logger.info("Card reader polling started")

    yield

    # Shutdown
    logger.info("Shutting down usbutler...")

    # Stop button monitoring
    door_control_service.stop_button_monitoring()
    logger.info("Button monitoring stopped")

    if card_reader_polling:
        card_reader_polling.stop()
        logger.info("Card reader polling stopped")


# Create FastAPI application
app = FastAPI(
    title="USButler",
    description="Access control system with NFC card reader support",
    version="2.0.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(users_router, prefix="/api")
app.include_router(doors_router, prefix="/api")
app.include_router(identifiers_router, prefix="/api")
app.include_router(ui_router)


@app.get("/api")
async def api_root():
    """API root endpoint."""
    return {
        "name": "USButler",
        "version": "2.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
