import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings, get_settings
from app.services.review_service import ReviewTaskService


class ReviewScheduler:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self._run_mock_review,
            "interval",
            seconds=self.settings.scheduler_interval_seconds,
            id="mock-code-review-task",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _run_mock_review(self) -> None:
        service = ReviewTaskService(self.settings)
        task = service.create_mock_task()
        await asyncio.to_thread(service.review_task, task)
