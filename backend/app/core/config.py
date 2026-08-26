"""Central runtime configuration, read from environment variables.

Local dev: values below match infra/docker-compose.yml defaults.
Prod: override every field via real environment variables / secrets — never
edit the defaults here for a deployment.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"

    # Postgres
    database_url: str = "postgresql+psycopg2://caseflow:caseflow@localhost:5432/caseflow"

    # Redis (used by the arq worker that runs the A→B→C→D→F pipeline, phase 2)
    redis_url: str = "redis://localhost:6379/0"

    # Object storage for uploaded case documents (MinIO, S3-compatible)
    s3_endpoint: str = "localhost:9000"
    s3_access_key: str = "caseflow"
    s3_secret_key: str = "caseflow-secret"
    s3_bucket: str = "case-documents"
    s3_secure: bool = False

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12  # 12h session

    # CORS — the Vite dev server origin; add prod frontend origin via env in deployment
    cors_origins: list[str] = ["http://localhost:5173"]

    # LLM (Agent A/B/C/D/F orchestration)
    # 这是启动时的兜底默认值——运行时实际用哪个后端由 app_settings 表的
    # llm_provider 行决定（Prompt 后台页面可切换 minimax/kimi），数据库里
    # 没有这一行时才落回这个值。见 app/services/settings_service.py。
    llm_provider: str = "minimax"  # "minimax" | "kimi" | "anthropic"
    # MiniMax-M3 spends part of this budget on `thinking` before it ever gets
    # to the tool call — 16k was observed to truncate mid-response on Agent F
    # (the heaviest agent: full case context + several cutpoints). MiniMax's
    # own docs recommend up to 131072 for M3; 65536 is a middle ground.
    llm_max_tokens: int = 65536

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"

    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_model: str = "MiniMax-M3"

    # Kimi K3（Moonshot），OpenAI 兼容协议，见 doc/需求细节澄清.md 底部贴的
    # 官方文档节选。跟 MiniMax 的关键差异：真的支持 tool_choice="required"，
    # 不用像 MiniMax 那样靠 system prompt 硬提示 + content 兜底解析。
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k3"
    # K3 默认 reasoning_effort=max，思考链条拉满——结构化抽取这种任务不一定
    # 需要那么深的推理，调低换响应速度。支持 low/high/max（Kimi 官方三档），
    # 复杂病例的抽取质量要不要打折扣，得靠真实跑测验证，不是想当然。
    kimi_reasoning_effort: str = "low"


@lru_cache
def get_settings() -> Settings:
    return Settings()
