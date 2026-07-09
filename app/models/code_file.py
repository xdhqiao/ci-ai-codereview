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
    issue_show = BooleanField(required=False, default=True)
    comment_line_number = IntField(required=False, default=0)
    confidence_level = FloatField(required=False)
    re_review_description = StringField(required=False)
    re_review_status = IntField(required=False, default=0)
    feedback_type = StringField(required=False)
    feedback_content = StringField(required=False)
    feedback_effect = BooleanField(required=False)


class CodeBlock(EmbeddedDocument):
    block_id = IntField(required=True, default=0)
    block_hash = StringField(required=False)
    contents = ListField(StringField(), required=True)
    comment = StringField(required=True, default="")
    logic_score = IntField(required=True, default=0)
    performance_score = IntField(required=True, default=0)
    security_score = IntField(required=True, default=0)
    readable_score = IntField(required=True, default=0)
    code_style_score = IntField(required=True, default=0)
    comment_line_number = IntField(required=False, default=0)
    issues = ListField(EmbeddedDocumentField(Issue), required=False, default=list)
    process_time = IntField(required=False, default=0)
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
