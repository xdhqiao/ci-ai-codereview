import os

os.environ["APP_ENABLE_SCHEDULER"] = "false"
os.environ["LLM_MOCK_ENABLED"] = "true"
os.environ["MONGO_MOCK"] = "true"
os.environ["MONGODB_DB"] = "ci_ai_codereview_test"
os.environ["REVIEW_EXCLUDE_PATHS"] = ""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import connect_to_mongo, disconnect_mongo
from app.main import app
from app.models.code_file import CodeFileModel
from app.models.project import ProjectModel
from app.models.task import TaskModel
from app.models.task_trigger import TaskTriggerModel


@pytest.fixture(autouse=True)
def clean_database():
    get_settings.cache_clear()
    settings = get_settings()
    connect_to_mongo(settings)
    TaskModel.drop_collection()
    TaskTriggerModel.drop_collection()
    CodeFileModel.drop_collection()
    ProjectModel.drop_collection()
    yield
    connect_to_mongo(settings)
    TaskModel.drop_collection()
    TaskTriggerModel.drop_collection()
    CodeFileModel.drop_collection()
    ProjectModel.drop_collection()
    disconnect_mongo(settings)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
