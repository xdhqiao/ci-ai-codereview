import logging

from app.models.task import TaskModel


logger = logging.getLogger(__name__)


class ReviewNotificationService:
    def send_review_completed(self, task: TaskModel) -> None:
        logger.info(
            "Demo review completion email: project=%s review=%s base=%s task_id=%s",
            task.project_id,
            task.review_version,
            task.copy_from_version,
            task.id,
        )
