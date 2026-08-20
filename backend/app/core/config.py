"""
RouteEase core configuration.
Loads environment variables with validation.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Free Routing APIs ---
    osrm_base_url: str = Field(
        default="https://router.project-osrm.org",
        description="OSRM backend URL for routing",
    )
    overpass_base_url: str = Field(
        default="https://overpass-api.de/api/interpreter",
        description="Overpass API URL for pitstops",
    )

    # --- LLM Configuration ---
    llm_provider: str = Field(
        default="ollama",
        description="LLM provider: ollama | lmstudio | openai | anthropic | gemini | openrouter",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server base URL",
    )
    ollama_model: str = Field(
        default="llama3.2",
        description="Ollama model name",
    )
    lm_studio_base_url: str = Field(
        default="http://localhost:1234/v1",
        description="LM Studio server base URL",
    )
    lm_studio_model: str = Field(
        default="",
        description="LM Studio model name (optional, will use loaded model if empty)",
    )
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI base URL")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model name")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    gemini_api_key: str = Field(default="", description="Gemini API key")
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    openrouter_model: str = Field(default="poolside/laguna-s-2.1:free", description="OpenRouter model")

    # --- Server ---
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=True, description="Debug mode")

    # --- CORS ---
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        description="Comma-separated allowed CORS origins",
    )

    ola_maps_api_key: str = Field(
        default="",
        description="Ola Maps API key (Krutrim Cloud)",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS origins string into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        """Check if LLM provider appears configured (does not verify connectivity)."""
        if self.llm_provider in ("ollama", "lmstudio"):
            return True  # Local providers checked at runtime
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        if self.llm_provider == "openrouter":
            return bool(self.openrouter_api_key)
        return False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings()
