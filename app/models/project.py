from datetime import datetime, timezone

from mongoengine import (
    DateTimeField,
    DictField,
    Document,
    EmbeddedDocument,
    EmbeddedDocumentField,
    IntField,
    ListField,
    StringField,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Review(EmbeddedDocument):
    id = StringField(required=True)
    state = IntField(required=True)
    score = IntField(required=False, default=0)
    create_time = DateTimeField(required=True)


class ProjectModel(Document):
    meta = {"collection": "ai_codereview_project", "indexes": ["project_id"]}

    project_id = StringField(required=True)
    project_name = StringField(required=False, default="")
    project_url = StringField(required=False)
    git_project_id = IntField(required=False)
    owner = ListField(StringField(), required=False, default=list)
    developers = ListField(StringField(), required=False, default=list)
    exclude_path = ListField(StringField(), required=False, default=list)
    version_control_system = StringField(required=True)
    history_reviews = DictField(field=EmbeddedDocumentField(Review), required=False, default=dict)
    scan_round = IntField(required=False, default=0)
    created_by = StringField(required=False, default="")
    create_time = DateTimeField(default=utc_now, required=True)
    updated_by = StringField(required=False, default="")
    update_time = DateTimeField(required=False)
    default_base_branch = StringField(required=False, default="")
