from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "ai-kubernetes-agent"

    # LLM: any OpenAI-compatible endpoint (OpenRouter, OpenAI, Gemini, Ollama, ...)
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 2

    # Auth: "password" (single admin password) or "none" (protect it with your own ingress/SSO)
    auth_mode: str = "password"
    admin_password: str = ""
    secret_key: str = ""  # signs login tokens; generated and stored in data_dir if empty
    session_hours: int = 12

    # Storage for investigation history (SQLite)
    data_dir: str = "./data"

    # Kubernetes: empty kubeconfig_path = in-cluster ServiceAccount (or kubectl's default kubeconfig)
    kubeconfig_path: str = ""
    allowed_namespace: str = ""  # set when installed with namespace-only RBAC

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
