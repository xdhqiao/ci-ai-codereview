from mongoengine import BooleanField, DateTimeField, DictField, ListField, StringField

from app.models.task import TaskBaseModel


class TaskSnapshotModel(TaskBaseModel):
    meta = {
        "collection": "ai_codereview_task_snapshot",
        "indexes": [
            {"fields": ["snapshot_id"], "unique": True},
            {"fields": ["task_id", "trigger_revision"], "unique": True},
            ("project_id", "review_version", "copy_from_version", "-create_time"),
            ("state", "-create_time"),
        ],
    }

    task_id = StringField(required=True)
    snapshot_id = StringField(required=True)
    changed_files = ListField(StringField(), required=False, default=list)
    changed_file_names = ListField(StringField(), required=False, default=list)
    changed_blocks = ListField(DictField(), required=False, default=list)
    removed_file_names = ListField(StringField(), required=False, default=list)
    usage_baseline = DictField(required=False, default=dict)
    completion_log_sent = BooleanField(required=False, default=False)
    completion_time = DateTimeField(required=False)
