import sys
from pathlib import Path

# Add delta directory to Python path for absolute imports
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import (
    users_router,
    identifiers_router,
    doors_router,
    user_identifiers_router,
)

# Create FastAPI application
app = FastAPI(
    title="USButler Delta API",
    description="Access control management API with file-based JSON database",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(users_router, prefix="/api")
app.include_router(identifiers_router, prefix="/api")
app.include_router(doors_router, prefix="/api")
app.include_router(user_identifiers_router, prefix="/api")


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "USButler Delta API is running"}


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
