from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import connect_to_mongo, disconnect_mongo
from app.core.exceptions import register_exception_handlers
from app.routes import code_files, health, tasks
from app.services.scheduler import ReviewScheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    connect_to_mongo(settings)
    scheduler = ReviewScheduler(settings)
    if settings.app_enable_scheduler:
        scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
        disconnect_mongo(settings)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(code_files.router)
    return app


app = create_app()
