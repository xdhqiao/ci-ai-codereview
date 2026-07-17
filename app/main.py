from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import connect_to_mongo, disconnect_mongo
from app.core.exceptions import register_exception_handlers
from app.routes import admin, code_files, health, reports, tasks
from app.services.scheduler import ReviewScheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    connect_to_mongo(settings)
    scheduler = ReviewScheduler(settings)
    app.state.review_scheduler = scheduler
    if settings.app_enable_scheduler:
        scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        await scheduler.wait_for_shutdown(settings.scheduler_shutdown_grace_seconds)
        disconnect_mongo(settings)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(code_files.router)
    app.include_router(admin.router)
    app.include_router(reports.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
    return app


app = create_app()
