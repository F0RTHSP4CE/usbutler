"""Main FastAPI application."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.migrations import run_migrations
from app.dependencies import create_services_for_thread, get_registry
from app.emv.nfc_reader import NFCReader
from app.routers import (
    doors_router,
    identifiers_router,
    pos_router,
    users_router,
    ui_router,
)
from app.services.card_reader import CardReaderService
from app.services.card_reader_polling import CardReaderPollingService
from app.services.uid_writer import ACR122UidWriter
from app.services.uid_rotation_service import UidRotationService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

nfc_reader = NFCReader()
card_reader_service = CardReaderService(nfc_reader)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting usbutler...")
    try:
        run_migrations()
    except Exception:
        logger.exception("Database migration failed")
        raise

    registry = get_registry()
    door_control = registry.door_control_service

    with create_services_for_thread() as services:
        if settings.UID_ROTATION_ENABLED:
            UidRotationService(services.db).initialize_enabled_users()
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
        uid_writer=ACR122UidWriter(
            nfc_reader,
            settings.MIFARE_CLASSIC_KEY_A,
            max_attempts=settings.UID_WRITE_MAX_ATTEMPTS,
            retry_delay_seconds=settings.UID_WRITE_RETRY_DELAY_SECONDS,
        ),
    )
    registry.card_reader_polling = card_reader_polling
    card_reader_polling.start()
    logger.info("Card reader polling started")

    yield

    logger.info("Shutting down usbutler...")
    door_control.stop_button_monitoring()
    if registry.card_reader_polling:
        registry.card_reader_polling.stop()


app = FastAPI(
    title="USButler",
    version="2.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
)
app.include_router(users_router, prefix="/api")
app.include_router(doors_router, prefix="/api")
app.include_router(identifiers_router, prefix="/api")
app.include_router(pos_router, prefix="/api")
app.include_router(ui_router)


@app.get("/api")
async def api_root():
    return {"name": "USButler", "version": "2.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
