from pathlib import Path

from app.core.config import Settings, get_settings
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.services.review_service import ReviewTaskService


class FakeRetryLLMClient:
    is_mock = False

    def __init__(self, comments):
        self.comments = comments
        self.chat_count = 0

    def complete_json(self, messages, tools=None):
        return {
            "comment": "plan ok",
            "logic_score": 80,
            "performance_score": 80,
            "security_score": 80,
            "readable_score": 80,
            "code_style_score": 80,
        }

    def chat(self, messages, tools=None):
        self.chat_count += 1
        if self.chat_count == 1:
            return {"role": "assistant", "content": "not-json"}
        return {"role": "assistant", "content": self.comments}

    def _extract_json(self, content):
        import json

        return json.loads(content)


def test_incremental_review_saves_code_file_and_issues(tmp_path: Path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    (base_dir / "src").mkdir(parents=True)
    (head_dir / "src").mkdir(parents=True)
    (base_dir / "src" / "app.py").write_text(
        "def run(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (head_dir / "src" / "app.py").write_text(
        "def run(value):\n"
        "    secret = 'plain-text'\n"
        "    return eval(value)\n",
        encoding="utf-8",
    )

    task = TaskModel(
        project_id="review-project",
        review_version=str(head_dir),
        copy_from_version=str(base_dir),
        task_type=1,
        state=0,
    ).save()

    service = ReviewTaskService(get_settings())
    reviewed_task = service.review_task(task)

    assert reviewed_task.state == 2
    assert reviewed_task.file_num == 1
    assert reviewed_task.comment_line_number >= 2

    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "src/app.py"
    assert code_file.code_blocks[0].contents[0][6] in {" ", "-", "+"}
    assert any(line[6] == "+" for line in code_file.code_blocks[0].contents)
    assert max(issue.severity for issue in code_file.code_blocks[0].issues) == 5


def test_full_scan_reviews_all_lines(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "script.py").write_text("print('hello')\n", encoding="utf-8")

    task = TaskModel(
        project_id="scan-project",
        review_version=str(target_dir),
        copy_from_version="",
        task_type=2,
        state=0,
    ).save()

    reviewed_task = ReviewTaskService(get_settings()).review_task(task)

    assert reviewed_task.state == 2
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "script.py"
    assert code_file.add_code_line_num == 1


def test_version_names_resolve_under_repository_root(tmp_path: Path):
    repository_root = tmp_path / "repositories"
    base_dir = repository_root / "demo_c" / "master"
    head_dir = repository_root / "demo_c" / "wip_qiaodahai_just_demo"
    base_dir.mkdir(parents=True)
    head_dir.mkdir(parents=True)
    (base_dir / "main.c").write_text("int main(void) {\n    return 0;\n}\n", encoding="utf-8")
    (head_dir / "main.c").write_text("int main(void) {\n    char secret[] = \"demo\";\n    return 0;\n}\n", encoding="utf-8")

    task = TaskModel(
        project_id="demo_c",
        review_version="wip_qiaodahai_just_demo",
        copy_from_version="master",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, code_repository_root=str(repository_root))

    reviewed_task = ReviewTaskService(settings).review_task(task)

    assert reviewed_task.task_type == 1
    assert reviewed_task.state == 2
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "main.c"
    assert code_file.task_type == 1


def test_zero_version_means_full_scan_under_repository_root(tmp_path: Path):
    repository_root = tmp_path / "repositories"
    target_dir = repository_root / "demo_c" / "master"
    target_dir.mkdir(parents=True)
    (target_dir / "main.c").write_text("int main(void) {\n    return 0;\n}\n", encoding="utf-8")

    task = TaskModel(
        project_id="demo_c",
        review_version="master",
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, code_repository_root=str(repository_root))

    reviewed_task = ReviewTaskService(settings).review_task(task)

    assert reviewed_task.task_type == 2
    assert reviewed_task.state == 2
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "main.c"
    assert code_file.task_type == 2
    assert code_file.add_code_line_num == 3


def test_main_task_retries_when_json_parse_fails(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="retry-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=False, llm_json_retry_times=1)
    service = ReviewTaskService(settings)
    service.llm_client = FakeRetryLLMClient(
        '{"issues":[{"type":"security","severity":4,"description":"desc","suggestion":"fix","issue_line_numbers":"1"}]}'
    )

    reviewed_task = service.review_task(task)

    assert reviewed_task.comment_line_number == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.code_blocks[0].issues[0].description == "desc"
    assert code_file.code_blocks[0].failure_message == ""


def test_duplicate_issues_are_merged_within_current_file(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="merge-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=False, llm_json_retry_times=1)
    service = ReviewTaskService(settings)
    service.llm_client = FakeRetryLLMClient(
        '{"issues":['
        '{"type":"security","severity":4,"description":"same","suggestion":"fix","issue_line_numbers":"1"},'
        '{"type":"security","severity":4,"description":"same","suggestion":"fix","issue_line_numbers":"1"}'
        "]}"
    )

    reviewed_task = service.review_task(task)

    assert reviewed_task.comment_line_number == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert len(code_file.code_blocks[0].issues) == 1
