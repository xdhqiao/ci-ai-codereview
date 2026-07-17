from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ci-ai-codereview"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_enable_scheduler: bool = False
    scheduler_interval_seconds: int = 5
    scheduler_lease_seconds: int = 120
    scheduler_max_task_retries: int = 3
    scheduler_retry_backoff_seconds: int = 30
    scheduler_retry_backoff_max_seconds: int = 900
    scheduler_shutdown_grace_seconds: int = 150

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
    full_scan_max_tool_rounds: int = 60
    llm_max_consecutive_empty_rounds: int = 3
    llm_file_timeout_seconds: int = 600
    llm_json_retry_times: int = 2
    llm_context_compress_rounds: int = 4
    llm_context_compress_token_threshold: int = 0
    llm_max_context_tokens: int = 58888
    llm_context_soft_ratio: float = 0.60
    llm_context_hard_ratio: float = 0.80
    llm_context_compression_llm_enabled: bool = True
    llm_context_keep_recent_messages: int = 6
    llm_context_summary_max_chars: int = 2000
    llm_mock_enabled: bool = True

    diff_token_threshold: int = 10000
    diff_context_lines: int = 10
    scan_batch_size: int = 20
    scan_batch_strategy: str = "by-language"
    full_scan_token_budget: int = 0
    full_scan_batch_dedup_enabled: bool = True
    full_scan_batch_dedup_llm_enabled: bool = True
    full_scan_batch_dedup_min_comments: int = 4
    full_scan_project_summary_enabled: bool = True
    full_scan_project_summary_llm_enabled: bool = True
    full_scan_project_summary_max_issues: int = 200
    review_resume_enabled: bool = True
    code_repository_root: str = ""
    review_exclude_dirs: str = ".git,.opencodereview,__pycache__,node_modules,.venv,venv,dist,build,.pytest_cache"
    review_exclude_paths: str = (
        "MCAL,Math,General,COMM,CANVector,main.c,Wdg,Smu,SafeTlib,SafeTpack,ERU_BSW,"
        "Eth_generated,Dem,DemConfig,FiM,FiMConfig,VStdLib,Etpu,freertos,FW_LIB,StartUp,"
        "Os_Stubs.c,Os_TaskInfr.c,.vscode,.history,**pycache**,BootloaderPlus_CData.c,"
        "PrjVer.c,PrjVer.h,SoftVer_Release.h"
    )
    review_allowed_extensions: str = Field(
        default=(
            ".py,.js,.jsx,.ts,.tsx,.go,.java,.kt,.kts,.c,.h,.cpp,.hpp,.cc,.cs,"
            ".rs,.php,.rb,.swift,.scala,.sql,.yaml,.yml,.json,.toml,.ini,.md,"
            ".sh,.bash,.ps1,.html,.css,.scss,.vue"
        )
    )
    review_rules_path: str = ""
    review_relocation_enabled: bool = True
    review_filter_enabled: bool = True
    review_filter_min_confidence: float = 0.45
    review_evidence_required: bool = True
    review_line_evidence_min_similarity: float = 0.55
    review_allow_heuristic_relocation: bool = False
    review_change_manifest_limit: int = 500
    review_related_files_enabled: bool = True
    review_related_file_limit: int = 8
    review_related_diff_max_chars: int = 12000
    review_static_analysis_enabled: bool = True
    review_static_analysis_sarif_paths: str = ""
    review_static_analysis_max_findings: int = 2000
    review_static_analysis_max_report_bytes: int = 20 * 1024 * 1024
    review_tool_max_read_lines: int = 500
    review_tool_max_search_matches: int = 100
    review_tool_max_file_bytes: int = 2 * 1024 * 1024
    review_tool_timeout_seconds: int = 10
    review_semantic_index_enabled: bool = True
    review_semantic_index_max_files: int = 5000
    review_semantic_index_max_file_bytes: int = 2 * 1024 * 1024
    review_semantic_index_max_results: int = 100
    review_semantic_index_build_timeout_seconds: int = 60

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
    def excluded_path_list(self) -> list[str]:
        return [item.strip() for item in self.review_exclude_paths.split(",") if item.strip()]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.review_allowed_extensions.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
