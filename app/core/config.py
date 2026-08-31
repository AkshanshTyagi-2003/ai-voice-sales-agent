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
    #
    # Twilio is retained for compatibility and for WhatsApp messaging.
    #
    # The active outbound voice provider is Retell.
    # ------------------------------------------------------------------

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_whatsapp_from: str = ""

    # ------------------------------------------------------------------
    # WhatsApp configuration
    # ------------------------------------------------------------------
    #
    # This project uses the existing Twilio credentials for outbound
    # WhatsApp messages.
    #
    # whatsapp_phone_number should contain the Twilio WhatsApp sender.
    #
    # Examples:
    #
    # WHATSAPP_PHONE_NUMBER=whatsapp:+14155238886
    #
    # or:
    #
    # WHATSAPP_PHONE_NUMBER=+14155238886
    #
    # The webhook sender normalizes it to the whatsapp: format.
    # ------------------------------------------------------------------

    whatsapp_api_key: str = ""
    whatsapp_phone_number: str = ""

    # ------------------------------------------------------------------
    # Generic provider fields
    # ------------------------------------------------------------------

    telephony_api_key: str = ""
    telephony_phone_number: str = ""

    speech_to_text_api_key: str = ""
    text_to_speech_api_key: str = ""

    # ------------------------------------------------------------------
    # Retell AI configuration
    # ------------------------------------------------------------------
    #
    # RETELL_API_KEY:
    # Authenticates requests from this backend to Retell.
    #
    # IMPORTANT:
    # The Retell API key used for webhook verification must be the
    # API key that has the Retell "webhook" badge.
    #
    # RETELL_AGENT_ID:
    # Identifies the Retell AI agent that handles the conversation.
    #
    # RETELL_PHONE_NUMBER:
    # The Retell-managed phone number used for outbound calls.
    #
    # Never hard-code these credentials.
    # ------------------------------------------------------------------

    retell_api_key: str = ""
    retell_agent_id: str = ""
    retell_phone_number: str = ""

    # ------------------------------------------------------------------
    # Public application URL
    # ------------------------------------------------------------------
    #
    # Example:
    #
    # PUBLIC_BASE_URL=https://your-app.up.railway.app
    #
    # This is used by external providers to reach the application.
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