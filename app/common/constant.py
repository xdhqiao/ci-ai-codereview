from enum import Enum, IntEnum


FULL_SCAN_BASE_VERSION = "0_version"
SEVERE_ISSUE_SEVERITY = 5
MANUAL_RETRY_PRIORITY = 100
EMPTY_FILE_AUTHOR_QUERY_VALUE = "__empty__"
EMPTY_FILE_AUTHOR_DISPLAY_NAME = "空"


class TaskType(Enum):
    DEV_VERSION = 1, "dev_version"
    PRD_VERSION = 2, "prd_version"
    FULL_SCAN = 3, "full_scan"

    def __new__(cls, value: int, description: str) -> "TaskType":
        member = object.__new__(cls)
        member._value_ = value
        member.description = description
        return member

    @property
    def is_incremental(self) -> bool:
        return self in {TaskType.DEV_VERSION, TaskType.PRD_VERSION}

    @classmethod
    def incremental_values(cls) -> tuple[int, int]:
        return cls.DEV_VERSION.value, cls.PRD_VERSION.value


class TaskState(IntEnum):
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    PARTIAL = 3
    PREPARING = 4


class ReviewState(IntEnum):
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3


class FeedbackType(str, Enum):
    AGREE = "agree"
    REJECT = "reject"


def is_incremental_task_type(value: int | None) -> bool:
    return value in TaskType.incremental_values()
