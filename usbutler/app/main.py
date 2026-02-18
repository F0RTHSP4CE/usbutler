"""Main FastAPI application."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.database import init_db
from app.dependencies import create_services_for_thread, get_registry
from app.emv.nfc_reader import NFCReader
from app.routers import (
    doors_router,
    identifiers_router,
    public_router,
    users_router,
    ui_router,
)
from app.services.card_reader import CardReaderService
from app.services.card_reader_polling import CardReaderPollingService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

nfc_reader = NFCReader()
card_reader_service = CardReaderService(nfc_reader)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting usbutler...")
    init_db()

    registry = get_registry()
    door_control = registry.door_control_service

    with create_services_for_thread() as services:
        doors = services.doors.get_all()
        if doors:
            door_control.start_button_monitoring(doors)
            logger.info(f"Button monitoring started for {len(doors)} doors")

    card_reader_polling = CardReaderPollingService(
        card_reader_service=card_reader_service,
        door_control_service=door_control,
        session_factory=create_services_for_thread,
        poll_interval=settings.CARD_READER_POLL_INTERVAL,
        default_door_id=settings.DEFAULT_DOOR_ID,
    )
    registry.card_reader_polling = card_reader_polling
    card_reader_polling.start()
    logger.info("Card reader polling started")

    yield

    logger.info("Shutting down usbutler...")
    door_control.stop_button_monitoring()
    if registry.card_reader_polling:
        registry.card_reader_polling.stop()


app = FastAPI(title="USButler", version="2.0.0", lifespan=lifespan)
app.include_router(users_router, prefix="/api")
app.include_router(doors_router, prefix="/api")
app.include_router(identifiers_router, prefix="/api")
app.include_router(public_router, prefix="/api")
app.include_router(ui_router)


@app.get("/api")
async def api_root():
    return {"name": "USButler", "version": "2.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
