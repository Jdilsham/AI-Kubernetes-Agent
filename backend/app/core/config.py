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

    # Claude (Anthropic API). When a key is set, the AI investigates in a loop: it picks read-only kubectl
    # commands itself, reads the output and decides the next step. Without a key, the OpenRouter path above is used.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    # auto = Claude loop when a Claude key is set, otherwise one prompt; loop = also investigate step by step with
    # an OpenAI-compatible model (needs a model with tool calling); single = always one prompt
    agent_mode: str = "auto"
    agent_max_steps: int = 15  # kubectl commands the AI may run per investigation
    agent_effort: str = "medium"  # low | medium | high: how hard the model thinks per step
    agent_timeout_seconds: int = 600  # wall-clock limit for the whole agent run

    # Per kubectl API request; slow links (Docker Desktop, VPN, remote AKS/EKS) may need more than 10s
    kubectl_request_timeout_seconds: int = 10

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
