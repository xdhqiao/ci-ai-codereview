from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ci-ai-codereview"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_enable_scheduler: bool = False
    scheduler_interval_seconds: int = 300

    mongodb_uri: str = "mongodb://mongodb:27017/ci_ai_codereview"
    mongodb_db: str = "ci_ai_codereview"
    mongodb_alias: str = "default"
    mongo_mock: bool = False

    llm_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 120
    llm_concurrency: int = 4
    llm_max_tool_rounds: int = 30
    llm_json_retry_times: int = 2
    llm_mock_enabled: bool = True

    diff_token_threshold: int = 10000
    diff_context_lines: int = 10
    code_repository_root: str = ""
    review_exclude_dirs: str = ".git,__pycache__,node_modules,.venv,venv,dist,build,.pytest_cache"
    review_allowed_extensions: str = Field(
        default=(
            ".py,.js,.jsx,.ts,.tsx,.go,.java,.kt,.kts,.c,.h,.cpp,.hpp,.cc,.cs,"
            ".rs,.php,.rb,.swift,.scala,.sql,.yaml,.yml,.json,.toml,.ini,.md,"
            ".sh,.bash,.ps1,.html,.css,.scss,.vue"
        )
    )

    mock_project_id: str = "mock-project"
    mock_parent_path: str = ""
    mock_copy_from_version: str = ""
    mock_review_version: str = "/app"
    mock_task_type: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def excluded_dir_set(self) -> set[str]:
        return {item.strip() for item in self.review_exclude_dirs.split(",") if item.strip()}

    @property
    def allowed_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.review_allowed_extensions.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
