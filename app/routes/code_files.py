from fastapi import APIRouter, Query

from app.core.exceptions import NotFoundError
from app.models.code_file import CodeFileModel
from app.schemas.code_file import CodeFileListResponse, CodeFileResponse

router = APIRouter(prefix="/code-files", tags=["code-files"])


@router.get("", response_model=CodeFileListResponse)
def list_code_files(
    task_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CodeFileListResponse:
    query = CodeFileModel.objects
    if task_id:
        query = query(task_id=task_id)
    query = query.order_by("-create_time")
    return CodeFileListResponse(
        items=[CodeFileResponse.from_model(code_file) for code_file in query.skip(offset).limit(limit)],
        total=query.count(),
    )


@router.get("/{code_file_id}", response_model=CodeFileResponse)
def get_code_file(code_file_id: str) -> CodeFileResponse:
    code_file = CodeFileModel.objects(id=code_file_id).first()
    if not code_file:
        raise NotFoundError("Code file not found")
    return CodeFileResponse.from_model(code_file)
