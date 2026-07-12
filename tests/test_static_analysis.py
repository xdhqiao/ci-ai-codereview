import json
from pathlib import Path

from app.core.config import Settings
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.services.review_service import ReviewTaskService
from app.services.static_analysis import SarifFindingLoader


def _write_sarif(path: Path, uri: str, line: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "name": "ExampleSAST",
                                "rules": [
                                    {
                                        "id": "c/buffer-overflow",
                                        "shortDescription": {"text": "Potential buffer overflow"},
                                        "helpUri": "https://example.invalid/rules/c-buffer-overflow",
                                    }
                                ],
                            }
                        },
                        "results": [
                            {
                                "ruleId": "c/buffer-overflow",
                                "level": "error",
                                "message": {"text": "Potential buffer overflow from strcpy"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": uri},
                                            "region": {"startLine": line, "endLine": line},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_sarif_loader_reads_structured_findings_and_rejects_path_traversal(tmp_path: Path):
    _write_sarif(tmp_path / ".opencodereview" / "valid.sarif", "src/main.c")
    _write_sarif(tmp_path / ".opencodereview" / "invalid.sarif", "../outside.c")
    settings = Settings(
        mongo_mock=True,
        review_static_analysis_sarif_paths=".opencodereview/*.sarif",
    )

    findings = SarifFindingLoader(settings).load(tmp_path)

    assert list(findings) == ["src/main.c"]
    finding = findings["src/main.c"][0]
    assert finding.analyzer == "ExampleSAST"
    assert finding.rule_id == "c/buffer-overflow"
    assert finding.start_line == 2
    assert finding.fingerprint


def test_sarif_finding_corroborates_issue_and_is_persisted(tmp_path: Path):
    review_dir = tmp_path / "master"
    review_dir.mkdir()
    (review_dir / "main.c").write_text(
        "int copy(char *dst, const char *src) {\n    strcpy(dst, src);\n    return 0;\n}\n",
        encoding="utf-8",
    )
    _write_sarif(review_dir / ".opencodereview" / "results.sarif", "main.c")
    task = TaskModel(
        project_id="sarif-project",
        review_version=str(review_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    service = ReviewTaskService(
        Settings(
            mongo_mock=True,
            llm_mock_enabled=True,
            review_static_analysis_sarif_paths=".opencodereview/results.sarif",
        )
    )

    reviewed = service.review_task(task)

    block = CodeFileModel.objects(task_id=str(task.id), file_name="main.c").first().code_blocks[0]
    issue = next(item for item in block.issues if item.static_corroborated)
    assert reviewed.state == 2
    assert block.static_findings[0]["rule_id"] == "c/buffer-overflow"
    assert issue.static_analysis_sources == ["ExampleSAST"]
    assert issue.static_analysis_rule_ids == ["c/buffer-overflow"]
    assert issue.confidence_level >= 0.95
    assert any(trace.stage == "static_analysis_corroboration" for trace in block.model_rounds)
    assert reviewed.developer_issue_summary["_static_analysis"] == {
        "finding_count": 1,
        "corroborated_issue_count": 1,
        "sources": {"ExampleSAST": 1},
    }
