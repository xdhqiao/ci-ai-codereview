from datetime import datetime

from pydantic import BaseModel

from app.models.code_file import CodeBlock, CodeFileModel, Issue, ModelRoundTrace, ToolCallTrace


class IssueResponse(BaseModel):
    issue_id: int | None
    description: str
    type: str
    severity: int
    suggestion: str
    issue_line_numbers: str | None
    existing_code: str
    suggestion_code: str
    evidence: str
    rule_id: str
    evidence_match_status: str
    evidence_match_score: float | None
    evidence_start_line: int
    evidence_end_line: int
    evidence_occurrence_count: int
    evidence_source: str
    location_confidence: float | None
    location_ambiguous: bool
    comment_line_number: int
    confidence_level: float | None
    original_issue_line_numbers: str
    relocation_status: str
    relocation_description: str
    filter_status: str
    filter_reason: str
    filter_counter_evidence: str
    static_corroborated: bool
    static_analysis_sources: list[str]
    static_analysis_rule_ids: list[str]
    static_analysis_fingerprints: list[str]
    duplicate_group_id: str
    duplicate_of: str

    @classmethod
    def from_model(cls, issue: Issue) -> "IssueResponse":
        return cls(
            issue_id=issue.issue_id,
            description=issue.description,
            type=issue.type,
            severity=issue.severity,
            suggestion=issue.suggestion,
            issue_line_numbers=issue.issue_line_numbers,
            existing_code=issue.existing_code or "",
            suggestion_code=issue.suggestion_code or "",
            evidence=issue.evidence or "",
            rule_id=issue.rule_id or "",
            evidence_match_status=issue.evidence_match_status or "",
            evidence_match_score=issue.evidence_match_score,
            evidence_start_line=issue.evidence_start_line or 0,
            evidence_end_line=issue.evidence_end_line or 0,
            evidence_occurrence_count=issue.evidence_occurrence_count or 0,
            evidence_source=issue.evidence_source or "",
            location_confidence=issue.location_confidence,
            location_ambiguous=bool(issue.location_ambiguous),
            comment_line_number=issue.comment_line_number or 0,
            confidence_level=issue.confidence_level,
            original_issue_line_numbers=issue.original_issue_line_numbers or "",
            relocation_status=issue.relocation_status or "",
            relocation_description=issue.relocation_description or "",
            filter_status=issue.filter_status or "",
            filter_reason=issue.filter_reason or "",
            filter_counter_evidence=issue.filter_counter_evidence or "",
            static_corroborated=bool(issue.static_corroborated),
            static_analysis_sources=list(issue.static_analysis_sources or []),
            static_analysis_rule_ids=list(issue.static_analysis_rule_ids or []),
            static_analysis_fingerprints=list(issue.static_analysis_fingerprints or []),
            duplicate_group_id=issue.duplicate_group_id or "",
            duplicate_of=issue.duplicate_of or "",
        )


class ModelRoundTraceResponse(BaseModel):
    stage: str
    round_index: int
    model: str
    request_summary: str
    response_summary: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    elapsed_ms: int
    finish_reason: str
    tool_call_count: int
    error_message: str

    @classmethod
    def from_model(cls, trace: ModelRoundTrace) -> "ModelRoundTraceResponse":
        return cls(
            stage=trace.stage,
            round_index=trace.round_index,
            model=trace.model or "",
            request_summary=trace.request_summary or "",
            response_summary=trace.response_summary or "",
            prompt_tokens=trace.prompt_tokens or 0,
            completion_tokens=trace.completion_tokens or 0,
            total_tokens=trace.total_tokens or 0,
            reasoning_tokens=trace.reasoning_tokens or 0,
            cached_tokens=trace.cached_tokens or 0,
            elapsed_ms=trace.elapsed_ms or 0,
            finish_reason=trace.finish_reason or "",
            tool_call_count=trace.tool_call_count or 0,
            error_message=trace.error_message or "",
        )


class ToolCallTraceResponse(BaseModel):
    stage: str
    round_index: int
    tool_call_id: str
    tool_name: str
    arguments: dict
    result_summary: str
    success: bool
    cached: bool
    elapsed_ms: int
    error_message: str

    @classmethod
    def from_model(cls, trace: ToolCallTrace) -> "ToolCallTraceResponse":
        return cls(
            stage=trace.stage,
            round_index=trace.round_index,
            tool_call_id=trace.tool_call_id or "",
            tool_name=trace.tool_name,
            arguments=trace.arguments or {},
            result_summary=trace.result_summary or "",
            success=bool(trace.success),
            cached=bool(trace.cached),
            elapsed_ms=trace.elapsed_ms or 0,
            error_message=trace.error_message or "",
        )


class CodeBlockResponse(BaseModel):
    block_id: int
    block_hash: str | None
    contents: list[str]
    comment: str
    plan_change_summary: str
    plan_risk_level: str
    plan_checkpoints: list[dict]
    related_files: list[dict]
    static_findings: list[dict]
    logic_score: int
    performance_score: int
    security_score: int
    readable_score: int
    code_style_score: int
    comment_line_number: int
    issues: list[IssueResponse]
    process_time: int
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_reasoning_tokens: int
    llm_cached_tokens: int
    llm_elapsed_ms: int
    memory_compression_count: int
    main_task_completed: bool
    main_task_completion_mode: str
    main_task_round_count: int
    model_rounds: list[ModelRoundTraceResponse]
    tool_calls: list[ToolCallTraceResponse]
    failure_message: str

    @classmethod
    def from_model(cls, block: CodeBlock) -> "CodeBlockResponse":
        return cls(
            block_id=block.block_id,
            block_hash=block.block_hash,
            contents=list(block.contents or []),
            comment=block.comment,
            plan_change_summary=block.plan_change_summary or "",
            plan_risk_level=block.plan_risk_level or "",
            plan_checkpoints=list(block.plan_checkpoints or []),
            related_files=list(block.related_files or []),
            static_findings=list(block.static_findings or []),
            logic_score=block.logic_score,
            performance_score=block.performance_score,
            security_score=block.security_score,
            readable_score=block.readable_score,
            code_style_score=block.code_style_score,
            comment_line_number=block.comment_line_number or 0,
            issues=[IssueResponse.from_model(issue) for issue in block.issues],
            process_time=block.process_time or 0,
            llm_prompt_tokens=block.llm_prompt_tokens or 0,
            llm_completion_tokens=block.llm_completion_tokens or 0,
            llm_total_tokens=block.llm_total_tokens or 0,
            llm_reasoning_tokens=block.llm_reasoning_tokens or 0,
            llm_cached_tokens=block.llm_cached_tokens or 0,
            llm_elapsed_ms=block.llm_elapsed_ms or 0,
            memory_compression_count=block.memory_compression_count or 0,
            main_task_completed=bool(block.main_task_completed),
            main_task_completion_mode=block.main_task_completion_mode or "",
            main_task_round_count=block.main_task_round_count or 0,
            model_rounds=[ModelRoundTraceResponse.from_model(trace) for trace in block.model_rounds],
            tool_calls=[ToolCallTraceResponse.from_model(trace) for trace in block.tool_calls],
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
    background: str
    background_source: str
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
    extra: dict

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
            background=code_file.background or "",
            background_source=code_file.background_source or "",
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
            extra=code_file.extra or {},
        )


class CodeFileListResponse(BaseModel):
    items: list[CodeFileResponse]
    total: int
