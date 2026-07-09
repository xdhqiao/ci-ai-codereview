from datetime import datetime, timezone

from mongoengine import DateTimeField, DictField, Document, IntField, StringField


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskModel(Document):
    meta = {
        "collection": "ai_codereview_task",
        "indexes": [("project_id", "review_version", "copy_from_version")],
    }

    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
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
    code_block_num = IntField(required=False, default=0)
    file_num = IntField(required=False, default=0)
    reviewed_file_num = IntField(required=False, default=0)
    add_code_line_num = IntField(required=False, default=0)
    comment_line_number = IntField(required=False, default=0)
    process_time = IntField(required=False, default=0)
    parent_path = StringField(required=False)
    developer_issue_summary = DictField(required=False, default=dict)
    created_by = StringField(required=False, default="")
    create_time = DateTimeField(default=utc_now, required=True)
    updated_by = StringField(required=False, default="")
    update_time = DateTimeField(required=False)
