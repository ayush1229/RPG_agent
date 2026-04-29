from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables / .env file.

    Supports both OpenRouter and Featherless (both are OpenAI-compatible).
    Set LLM_BASE_URL to the provider's API endpoint and LLM_API_KEY to your key.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM (Game Master) ─────────────────────────────────────────────────────
    llm_api_key: str
    llm_base_url: str
    llm_model: str

    # ── Persona model (NPC voice agent) ───────────────────────────────────────
    persona_model: str

    # ── Arbiter (tool calling — same key/URL, dedicated tool-use model) ───────
    arbiter_model: str

    # ── App ───────────────────────────────────────────────────────────────────
    app_name: str = "AI RPG Agent"
    app_debug: bool = False


# Singleton — import this everywhere
settings = Settings()
