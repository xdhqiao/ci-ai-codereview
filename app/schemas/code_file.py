from datetime import datetime

from pydantic import BaseModel

from app.models.code_file import CodeBlock, CodeFileModel, Issue


class IssueResponse(BaseModel):
    issue_id: int | None
    description: str
    type: str
    severity: int
    suggestion: str
    issue_line_numbers: str | None
    issue_show: bool | None
    comment_line_number: int
    confidence_level: float | None

    @classmethod
    def from_model(cls, issue: Issue) -> "IssueResponse":
        return cls(
            issue_id=issue.issue_id,
            description=issue.description,
            type=issue.type,
            severity=issue.severity,
            suggestion=issue.suggestion,
            issue_line_numbers=issue.issue_line_numbers,
            issue_show=issue.issue_show,
            comment_line_number=issue.comment_line_number or 0,
            confidence_level=issue.confidence_level,
        )


class CodeBlockResponse(BaseModel):
    block_id: int
    block_hash: str | None
    contents: list[str]
    comment: str
    logic_score: int
    performance_score: int
    security_score: int
    readable_score: int
    code_style_score: int
    comment_line_number: int
    issues: list[IssueResponse]
    process_time: int
    failure_message: str

    @classmethod
    def from_model(cls, block: CodeBlock) -> "CodeBlockResponse":
        return cls(
            block_id=block.block_id,
            block_hash=block.block_hash,
            contents=list(block.contents or []),
            comment=block.comment,
            logic_score=block.logic_score,
            performance_score=block.performance_score,
            security_score=block.security_score,
            readable_score=block.readable_score,
            code_style_score=block.code_style_score,
            comment_line_number=block.comment_line_number or 0,
            issues=[IssueResponse.from_model(issue) for issue in block.issues],
            process_time=block.process_time or 0,
            failure_message=block.failure_message or "",
        )


class CodeFileResponse(BaseModel):
    id: str
    task_id: str | None
    project_id: str
    review_version: str
    copy_from_version: str
    task_type: int | None
    file_name: str
    code_blocks: list[CodeBlockResponse]
    code_line_num: int
    add_code_line_num: int
    comment_line_number: int
    logic_score: int
    performance_score: int
    security_score: int
    readable_score: int
    code_style_score: int
    file_author: str
    create_time: datetime

    @classmethod
    def from_model(cls, code_file: CodeFileModel) -> "CodeFileResponse":
        return cls(
            id=str(code_file.id),
            task_id=code_file.task_id,
            project_id=code_file.project_id,
            review_version=code_file.review_version,
            copy_from_version=code_file.copy_from_version,
            task_type=code_file.task_type,
            file_name=code_file.file_name,
            code_blocks=[CodeBlockResponse.from_model(block) for block in code_file.code_blocks],
            code_line_num=code_file.code_line_num or 0,
            add_code_line_num=code_file.add_code_line_num or 0,
            comment_line_number=code_file.comment_line_number or 0,
            logic_score=code_file.logic_score,
            performance_score=code_file.performance_score,
            security_score=code_file.security_score,
            readable_score=code_file.readable_score,
            code_style_score=code_file.code_style_score,
            file_author=code_file.file_author or "",
            create_time=code_file.create_time,
        )


class CodeFileListResponse(BaseModel):
    items: list[CodeFileResponse]
    total: int
