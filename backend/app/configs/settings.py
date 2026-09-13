"""应用配置中心（基于 pydantic-settings）。

优先级：环境变量 > .env 文件 > 代码默认值。
敏感项（API key）由前端/设置页覆盖时加密存 PG，此处 .env 仅作开发兜底。
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 应用 ---
    app_name: str = "OpsMind"
    app_version: str = "0.1.0"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # --- 生产/私网部署 ---
    admin_password: str = "admin"  # 首启改掉；生产经 env 注入
    jwt_secret: str = "opsmind-dev-change-me-please-32chars!!"
    jwt_expire_minutes: int = 720  # 12h

    # --- 数据库（PG + pgvector 一体） ---
    database_url: str = "postgresql+psycopg://opsmind:opsmind@localhost:5432/opsmind"
    database_url_async: Optional[str] = None  # 缺省按 database_url 生成
    redis_url: Optional[str] = None  # 可选，不配则内存缓存

    @property
    def async_db_url(self) -> str:
        if self.database_url_async:
            return self.database_url_async
        return self.database_url.replace("postgresql+psycopg", "postgresql+asyncpg")

    # --- LLM（默认，前端设置可覆盖） ---
    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen-max"
    light_model: str = "qwen-max"  # 轻任务模型（压缩/摘要/记忆提炼/文档处理）
    llm_temperature: float = 0.2

    # --- 文档处理能力（多模态 / 轻任务 / 图片解析） ---
    docproc_api_key: str = ""
    docproc_base_url: str = ""      # 空=回落 openai_base_url
    docproc_model: str = ""         # 空=回落 light_model

    # --- 向量 embedding 能力 ---
    embedding_api_key: str = ""
    embedding_base_url: str = ""    # 空=回落 openai_base_url
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # --- 上下文压缩（D43） ---
    context_reserved: int = 10000  # min(10000, ctx*20%) 取小
    context_trigger_ratio: float = 0.8
    recent_message_n: int = 10
    summary_cap_min: int = 800
    summary_cap_max: int = 4000

    # --- 并发/限流（D47） ---
    llm_semaphore: int = 5          # 全局 LLM 并发
    report_gen_concurrency: int = 4 # 报告生成并发
    script_exec_concurrency: int = 5  # 脚本执行并发
    llm_rpm: int = 60               # 令牌桶：requests/min
    llm_daily_token_budget: int = 1_000_000

    # --- 调度（D17/D45） ---
    script_default_timeout: int = 30
    retry_max_attempts: int = 3
    retry_backoff_base: float = 1.0  # 1s/2s/4s
    diagnostic_concurrency: int = 2  # 并发诊断上限
    diagnostic_total_timeout: int = 60  # 总超时秒
    hypothesis_max: int = 6          # Planner 假设上限

    # --- 知识库/记忆（D41/D44） ---
    kb_top_k: int = 6
    kb_rrf_k: int = 60
    read_output_limit: int = 100
    output_disk_dir: Path = BASE_DIR / "outputs"
    output_disk_quota_gb: int = 2
    episodic_idle_minutes: int = 10
    semantic_min_episodes: int = 30
    semantic_half_life_days: int = 90

    # --- O4 / 输出规范（D45） ---
    pipeline_config_default: dict = {
        "p1_structure": True,
        "p2_evidence": True,
        "p3_conflict": True,
        "p4_out_of_bound": True,
        "p5_level_consistency": True,
    }

    # --- 路径 ---
    outputs_dir: Path = BASE_DIR / "outputs"
    uploads_dir: Path = BASE_DIR / "uploads"

    def ensure_dirs(self) -> None:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()