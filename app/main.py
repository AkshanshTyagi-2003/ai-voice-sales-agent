# main.py
"""
Application entry point.

Creates the FastAPI application and registers all API routers.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.calls import router as calls_router
from app.api.health import router as health_router
from app.api.scheduler import router as scheduler_router
from app.api.webhooks import router as webhooks_router
from app.api.whatsapp import router as whatsapp_router
from app.core.config import settings
from app.api.retell_webhook import router as retell_webhook_router


app = FastAPI(
    title=settings.app_name,
    description=(
        "AI-powered voice sales agent for "
        "e-commerce website lead qualification."
    ),
    version="1.0.0",
)

app.mount(
    "/assets",
    StaticFiles(directory="assets"),
    name="assets",
)

app.include_router(
    health_router
)

app.include_router(
    calls_router
)

app.include_router(
    webhooks_router
)

app.include_router(
    whatsapp_router
)

app.include_router(
    scheduler_router
)

app.include_router(
    retell_webhook_router
)

@app.get("/")
def root():
    """Return basic application information."""

    return {
        "app": settings.app_name,
        "status": "running",
        "version": "1.0.0",
    }