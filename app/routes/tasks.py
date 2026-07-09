from fastapi import APIRouter, Query, status

from app.core.exceptions import NotFoundError
from app.models.task import TaskModel
from app.schemas.task import TaskCreate, TaskListResponse, TaskResponse
from app.services.review_service import ReviewTaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> TaskResponse:
    task = TaskModel(
        project_id=payload.project_id,
        review_version=payload.review_version,
        copy_from_version=payload.copy_from_version,
        task_type=payload.task_type,
        state=payload.state,
        submitter=payload.submitter,
        parent_path=payload.parent_path,
        created_by=payload.created_by,
    )
    task.save()
    return TaskResponse.from_model(task)


@router.get("", response_model=TaskListResponse)
def list_tasks(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> TaskListResponse:
    query = TaskModel.objects.order_by("-create_time")
    items = [TaskResponse.from_model(task) for task in query.skip(offset).limit(limit)]
    return TaskListResponse(items=items, total=query.count())


@router.post("/mock", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_mock_task() -> TaskResponse:
    task = ReviewTaskService().create_mock_task()
    return TaskResponse.from_model(task)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    task = TaskModel.objects(id=task_id).first()
    if not task:
        raise NotFoundError("Task not found")
    return TaskResponse.from_model(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str) -> None:
    task = TaskModel.objects(id=task_id).first()
    if not task:
        raise NotFoundError("Task not found")
    task.delete()


@router.post("/{task_id}/review", response_model=TaskResponse)
def run_task_review(task_id: str) -> TaskResponse:
    task = ReviewTaskService().review_existing_task(task_id)
    return TaskResponse.from_model(task)
