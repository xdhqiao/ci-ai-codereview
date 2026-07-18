from datetime import datetime, timezone

from mongoengine import BooleanField, DateTimeField, DictField, Document, EmbeddedDocumentField, IntField, ListField, StringField

from app.models.code_file import ModelRoundTrace


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskBaseModel(Document):
    meta = {"abstract": True}

    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    review_version_path = StringField(required=False, default="")
    copy_from_version_path = StringField(required=False, default="")
    author_map_file = StringField(required=False, default="")
    submission_key = StringField(required=False)
    task_type = IntField(required=False)
    state = IntField(required=True)
    submitter = StringField(required=False)
    score = IntField(required=False, default=0)
    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    retry_count = IntField(required=False, default=0)
    manual_retry_count = IntField(required=False, default=0)
    dispatch_priority = IntField(required=False, default=0)
    retry_failed_only = BooleanField(required=False, default=False)
    automatic_retry_pending = BooleanField(required=False, default=False)
    retry_requested_time = DateTimeField(required=False)
    next_retry_time = DateTimeField(required=False)
    code_block_num = IntField(required=False, default=0)
    file_num = IntField(required=False, default=0)
    reviewed_file_num = IntField(required=False, default=0)
    resumed_file_num = IntField(required=False, default=0)
    skipped_file_num = IntField(required=False, default=0)
    incomplete_file_num = IntField(required=False, default=0)
    completion_status = StringField(required=False, default="")
    add_code_line_num = IntField(required=False, default=0)
    comment_line_number = IntField(required=False, default=0)
    process_time = IntField(required=False, default=0)
    estimated_token_num = IntField(required=False, default=0)
    consumed_estimated_token_num = IntField(required=False, default=0)
    token_budget_num = IntField(required=False, default=0)
    llm_prompt_tokens = IntField(required=False, default=0)
    llm_completion_tokens = IntField(required=False, default=0)
    llm_total_tokens = IntField(required=False, default=0)
    llm_elapsed_ms = IntField(required=False, default=0)
    llm_call_count = IntField(required=False, default=0)
    tool_call_summary = DictField(required=False, default=dict)
    task_model_rounds = ListField(EmbeddedDocumentField(ModelRoundTrace), required=False, default=list)
    project_summary = StringField(required=False, default="")
    parent_path = StringField(required=False)
    developer_issue_summary = DictField(required=False, default=dict)
    trigger_count = IntField(required=False, default=1)
    trigger_revision = IntField(required=False, default=1)
    lease_owner = StringField(required=False, default="")
    lease_token = StringField(required=False, default="")
    lease_expires_at = DateTimeField(required=False)
    heartbeat_time = DateTimeField(required=False)
    last_start_time = DateTimeField(required=False)
    interrupt_requested = BooleanField(required=False, default=False)
    completion_email_sent = BooleanField(required=False, default=False)
    created_by = StringField(required=False, default="")
    create_time = DateTimeField(default=utc_now, required=True)
    updated_by = StringField(required=False, default="")
    update_time = DateTimeField(required=False)


class TaskModel(TaskBaseModel):
    meta = {
        "collection": "ai_codereview_task",
        "indexes": [
            ("project_id", "review_version", "copy_from_version"),
            ("task_type", "state", "create_time"),
            ("state", "-create_time"),
            ("task_type", "-create_time"),
            "-create_time",
            ("-dispatch_priority", "task_type", "state", "create_time"),
            {"fields": ["submission_key"], "unique": True, "sparse": True},
        ],
    }

    latest_snapshot_id = StringField(required=False, default="")
