from datetime import datetime, timezone

from mongoengine import DateTimeField, Document, IntField, ListField, StringField


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskTriggerModel(Document):
    """Lightweight file selection captured for one trigger of a reusable task."""

    meta = {
        "collection": "ai_codereview_task_trigger",
        "indexes": [
            {"fields": ["task_id", "trigger_revision"], "unique": True},
            ("project_id", "review_version", "copy_from_version", "trigger_revision"),
            "-create_time",
        ],
    }

    task_id = StringField(required=True)
    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    trigger_revision = IntField(required=True)

    # report_file_names contains current files whose source changed in this trigger.
    report_file_names = ListField(StringField(), required=False, default=list)
    added_file_names = ListField(StringField(), required=False, default=list)
    changed_file_names = ListField(StringField(), required=False, default=list)
    reused_file_names = ListField(StringField(), required=False, default=list)
    removed_file_names = ListField(StringField(), required=False, default=list)

    create_time = DateTimeField(default=utc_now, required=True)
    update_time = DateTimeField(default=utc_now, required=True)
