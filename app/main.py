from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import connect_to_mongo, disconnect_mongo
from app.core.exceptions import register_exception_handlers
from app.routes import admin, code_files, feedback, health, reports, tasks
from app.services.data_migration import migrate_legacy_task_types
from app.services.scheduler import ReviewScheduler


def configure_application_logging() -> None:
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if any(getattr(handler, "_ci_ai_codereview", False) for handler in app_logger.handlers):
        return
    handler = logging.StreamHandler()
    handler._ci_ai_codereview = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    app_logger.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    connect_to_mongo(settings)
    migrate_legacy_task_types()
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
    configure_application_logging()
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(code_files.router)
    app.include_router(admin.router)
    app.include_router(feedback.router)
    app.include_router(reports.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
    return app


app = create_app()
