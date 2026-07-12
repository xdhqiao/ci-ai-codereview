from datetime import datetime, timezone

from mongoengine import (
    BooleanField,
    DateTimeField,
    DictField,
    Document,
    EmbeddedDocument,
    EmbeddedDocumentField,
    FloatField,
    IntField,
    ListField,
    StringField,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Issue(EmbeddedDocument):
    issue_id = IntField(required=False)
    description = StringField(required=True, default="")
    type = StringField(required=True, default="")
    severity = IntField(required=True, default=0)
    suggestion = StringField(required=True, default="")
    issue_line_numbers = StringField(required=False)
    existing_code = StringField(required=False, default="")
    suggestion_code = StringField(required=False, default="")
    evidence = StringField(required=False, default="")
    rule_id = StringField(required=False, default="")
    evidence_match_status = StringField(required=False, default="")
    evidence_match_score = FloatField(required=False)
    evidence_start_line = IntField(required=False, default=0)
    evidence_end_line = IntField(required=False, default=0)
    evidence_occurrence_count = IntField(required=False, default=0)
    evidence_source = StringField(required=False, default="")
    location_confidence = FloatField(required=False)
    location_ambiguous = BooleanField(required=False, default=False)
    issue_show = BooleanField(required=False, default=True)
    comment_line_number = IntField(required=False, default=0)
    confidence_level = FloatField(required=False)
    original_issue_line_numbers = StringField(required=False, default="")
    relocation_status = StringField(required=False, default="")
    relocation_description = StringField(required=False, default="")
    filter_status = StringField(required=False, default="")
    filter_reason = StringField(required=False, default="")
    filter_counter_evidence = StringField(required=False, default="")
    static_corroborated = BooleanField(required=False, default=False)
    static_analysis_sources = ListField(StringField(), required=False, default=list)
    static_analysis_rule_ids = ListField(StringField(), required=False, default=list)
    static_analysis_fingerprints = ListField(StringField(), required=False, default=list)
    duplicate_group_id = StringField(required=False, default="")
    duplicate_of = StringField(required=False, default="")
    re_review_description = StringField(required=False)
    re_review_status = IntField(required=False, default=0)
    feedback_type = StringField(required=False)
    feedback_content = StringField(required=False)
    feedback_effect = BooleanField(required=False)


class ModelRoundTrace(EmbeddedDocument):
    stage = StringField(required=True, default="")
    round_index = IntField(required=True, default=0)
    model = StringField(required=False, default="")
    request_summary = StringField(required=False, default="")
    response_summary = StringField(required=False, default="")
    prompt_tokens = IntField(required=False, default=0)
    completion_tokens = IntField(required=False, default=0)
    total_tokens = IntField(required=False, default=0)
    reasoning_tokens = IntField(required=False, default=0)
    cached_tokens = IntField(required=False, default=0)
    elapsed_ms = IntField(required=False, default=0)
    finish_reason = StringField(required=False, default="")
    tool_call_count = IntField(required=False, default=0)
    error_message = StringField(required=False, default="")
    create_time = DateTimeField(default=utc_now, required=True)


class ToolCallTrace(EmbeddedDocument):
    stage = StringField(required=True, default="main_task")
    round_index = IntField(required=True, default=0)
    tool_call_id = StringField(required=False, default="")
    tool_name = StringField(required=True, default="")
    arguments = DictField(required=False, default=dict)
    result_summary = StringField(required=False, default="")
    success = BooleanField(required=False, default=True)
    cached = BooleanField(required=False, default=False)
    elapsed_ms = IntField(required=False, default=0)
    error_message = StringField(required=False, default="")
    create_time = DateTimeField(default=utc_now, required=True)


class CodeBlock(EmbeddedDocument):
    block_id = IntField(required=True, default=0)
    block_hash = StringField(required=False)
    contents = ListField(StringField(), required=True)
    comment = StringField(required=True, default="")
    plan_change_summary = StringField(required=False, default="")
    plan_risk_level = StringField(required=False, default="")
    plan_checkpoints = ListField(DictField(), required=False, default=list)
    related_files = ListField(DictField(), required=False, default=list)
    static_findings = ListField(DictField(), required=False, default=list)
    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    comment_line_number = IntField(required=False, default=0)
    issues = ListField(EmbeddedDocumentField(Issue), required=False, default=list)
    process_time = IntField(required=False, default=0)
    llm_prompt_tokens = IntField(required=False, default=0)
    llm_completion_tokens = IntField(required=False, default=0)
    llm_total_tokens = IntField(required=False, default=0)
    llm_reasoning_tokens = IntField(required=False, default=0)
    llm_cached_tokens = IntField(required=False, default=0)
    llm_elapsed_ms = IntField(required=False, default=0)
    memory_compression_count = IntField(required=False, default=0)
    main_task_completed = BooleanField(required=False, default=False)
    main_task_completion_mode = StringField(required=False, default="")
    main_task_round_count = IntField(required=False, default=0)
    model_rounds = ListField(EmbeddedDocumentField(ModelRoundTrace), required=False, default=list)
    tool_calls = ListField(EmbeddedDocumentField(ToolCallTrace), required=False, default=list)
    gitlab_comment_id = StringField(required=False)
    failure_message = StringField(required=False, default="")


class CodeFileModel(Document):
    meta = {
        "collection": "ai_codereview_code_file",
        "indexes": ["project_id", ("project_id", "review_version", "copy_from_version"), "task_type"],
    }

    task_id = StringField(required=False)
    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    task_type = IntField(required=False)
    file_name = StringField(required=True)
    code_blocks = ListField(EmbeddedDocumentField(CodeBlock), default=list)
    code_line_num = IntField(required=False, default=0)
    add_code_line_num = IntField(required=False, default=0)
    comment_line_number = IntField(required=False, default=0)
    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    file_author = StringField(required=False, default="")
    created_by = StringField(required=False, default="")
    create_time = DateTimeField(default=utc_now, required=True)

    extra = DictField(required=False, default=dict)
