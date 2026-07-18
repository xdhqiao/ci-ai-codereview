from mongoengine import DateTimeField, DictField, Document, EmbeddedDocumentField, IntField, ListField, StringField

from app.models.code_file import CodeBlock, utc_now


class CodeFileSnapshotModel(Document):
    meta = {
        "collection": "ai_codereview_code_file_snapshot",
        "indexes": [
            {"fields": ["snapshot_id", "file_name"], "unique": True},
            "task_snapshot_id",
            "task_id",
            ("project_id", "review_version", "copy_from_version"),
        ],
    }

    task_snapshot_id = StringField(required=True)
    snapshot_id = StringField(required=True)
    task_id = StringField(required=True)
    source_file_id = StringField(required=True)
    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    task_type = IntField(required=False)
    file_name = StringField(required=True)
    state = IntField(required=False, default=0)
    source_hash = StringField(required=False, default="")
    trigger_revision = IntField(required=False, default=0)
    background = StringField(required=False, default="")
    background_source = StringField(required=False, default="")
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
    update_time = DateTimeField(required=False)
    extra = DictField(required=False, default=dict)
