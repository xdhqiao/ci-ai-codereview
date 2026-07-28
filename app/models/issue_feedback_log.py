from mongoengine import DateTimeField, Document, IntField, StringField

from app.models.code_file import utc_now


class IssueFeedbackLog(Document):
    meta = {
        "collection": "issue_feedback_log",
        "indexes": [
            "task_id",
            ("project_id", "review_version", "copy_from_version"),
            "create_time",
            ("file_author", "create_time"),
        ],
    }

    task_id = StringField(required=False)
    project_id = StringField(required=True)
    review_version = StringField(required=True)
    copy_from_version = StringField(required=True)
    task_type = IntField(required=False)
    file_name = StringField(required=True)
    file_author = StringField(required=False, default="")
    issue_line_numbers = StringField(required=False)
    severity = IntField(required=True, default=0)
    suggestion = StringField(required=True, default="")
    description = StringField(required=True, default="")
    feedback_type = StringField(required=False)
    feedback_content = StringField(required=False)
    create_time = DateTimeField(default=utc_now, required=True)
