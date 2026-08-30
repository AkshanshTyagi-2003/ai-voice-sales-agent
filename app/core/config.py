"""
Application configuration.

All environment-dependent values are centralized here so that the rest
of the application does not directly access environment variables.

Secrets and provider credentials are loaded from the local .env file
or from deployment environment variables.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    app_name: str = "AI Voice Sales Agent"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------

    host: str = "0.0.0.0"
    port: int = 8000

    # ------------------------------------------------------------------
    # Business configuration
    # ------------------------------------------------------------------

    business_name: str = "ElevateBox"

    # Number that receives the test/customer call.
    target_phone_number: str = "9536216821"

    # Optional human/sales-agent number.
    agent_phone_number: str = ""

    # ------------------------------------------------------------------
    # AI configuration
    # ------------------------------------------------------------------

    llm_api_key: str = ""
    llm_model: str = ""

    # ------------------------------------------------------------------
    # Twilio / Voice configuration
    # ------------------------------------------------------------------

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Generic provider fields kept for future provider switching.
    telephony_api_key: str = ""
    telephony_phone_number: str = ""

    speech_to_text_api_key: str = ""
    text_to_speech_api_key: str = ""

    # ------------------------------------------------------------------
    # WhatsApp configuration
    # ------------------------------------------------------------------

    whatsapp_api_key: str = ""
    whatsapp_phone_number: str = ""

    # ------------------------------------------------------------------
    # Public application URL
    # ------------------------------------------------------------------

    public_base_url: str = ""

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    timezone: str = "Asia/Kolkata"

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    database_path: str = "data/ai_voice_sales_agent.db"
    data_directory: str = "data"

    # ------------------------------------------------------------------
    # Submission assets
    # ------------------------------------------------------------------

    resume_path: str = "assets/resume.pdf"
    architecture_image_path: str = "assets/architecture.png"

    # ------------------------------------------------------------------
    # Environment loading
    # ------------------------------------------------------------------

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached application settings instance.

    The same configuration object is reused throughout the application.
    """

    return Settings()


settings = get_settings()