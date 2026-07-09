from app.core.database import ping_database
from app.models.task import TaskModel


def test_database_connection_and_model_save():
    assert ping_database() is True

    task = TaskModel(
        project_id="db-project",
        review_version="head",
        copy_from_version="base",
        task_type=1,
        state=0,
    ).save()

    assert TaskModel.objects(id=task.id).first().project_id == "db-project"
