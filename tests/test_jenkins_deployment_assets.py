from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_review_trigger_pipeline_preserves_client_contract():
    pipeline = _read("jenkins/Jenkinsfile.review-trigger")

    assert "agent { label 'linux-python' }" in pipeline
    expected_parameters = {
        "PROJECT_ID": "--project-id",
        "REVIEW_VERSION": "--review-version",
        "COPY_FROM_VERSION": "--copy-from-version",
        "REVIEW_VERSION_PATH": "--review-version-path",
        "COPY_FROM_VERSION_PATH": "--copy-from-version-path",
        "AUTHOR_MAP_FILE": "--author-map-file",
    }
    for parameter, option in expected_parameters.items():
        assert f"string(name: '{parameter}'" in pipeline
        assert option in pipeline
    assert "choice(name: 'TASK_TYPE'" in pipeline
    assert "--task-type" in pipeline
    assert "scripts/jenkins_trigger.py" in pipeline


def test_development_pipeline_promotes_only_tested_master_image():
    pipeline = _read("jenkins/Jenkinsfile.develop")

    assert "python -m pytest -q" in pipeline
    assert "docker build --pull" in pipeline
    assert '--build-arg "PYTHON_BASE_IMAGE=$PYTHON_BASE_IMAGE_VALUE"' in pipeline
    assert 'DOCKER_CONFIG="$(mktemp -d)"' in pipeline
    assert 'DOCKER_CONFIG="$WORKSPACE/' not in pipeline
    assert '"$CI_IMAGE_REPOSITORY:$FULL_COMMIT"' in pipeline
    assert '"$CI_IMAGE_REPOSITORY:release-$FULL_COMMIT"' in pipeline
    assert 'docker manifest inspect "$RELEASE_IMAGE"' in pipeline
    assert "when { branch 'master' }" in pipeline
    assert pipeline.count("currentBuild.displayName") == 1
    assert pipeline.index("currentBuild.displayName") > pipeline.index("when { branch 'master' }")
    assert "sh scripts/jenkins_deploy_release.sh" in pipeline


def test_production_pipeline_deploys_exact_promoted_snapshot():
    pipeline = _read("jenkins/Jenkinsfile.production")

    assert "string(name: 'COMMIT_SHORT'" in pipeline
    assert 'git merge-base --is-ancestor "$FULL_COMMIT" origin/master' in pipeline
    assert "release-${env.FULL_COMMIT}" in pipeline
    assert 'git archive --format=tar "$FULL_COMMIT"' in pipeline
    assert "sh scripts/jenkins_deploy_release.sh" in pipeline
    assert "Production Approval" in pipeline
    assert "docker build" not in pipeline


def test_blue_green_topology_separates_http_and_scheduler():
    slot_compose = _read("deploy/compose.slot.yml")
    gateway_compose = _read("deploy/compose.gateway.yml")
    deploy_script = _read("deploy/blue_green_deploy.sh")

    assert 'APP_ENABLE_SCHEDULER: "false"' in slot_compose
    assert 'APP_ENABLE_SCHEDULER: "true"' in slot_compose
    assert "/health/scheduler" in slot_compose
    assert "ports:" not in slot_compose
    assert "ports:" in gateway_compose
    assert 'flock -w "$DEPLOY_LOCK_TIMEOUT_SECONDS"' in deploy_script
    assert "nginx -s reload" in deploy_script
