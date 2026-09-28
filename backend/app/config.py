from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    assemblyai_api_key: str = ""
    database_url: str = (
        "postgresql+psycopg://afterhours:afterhours@localhost:5432/afterhours"
    )
    sqlite_url: str = "sqlite:///./clinic.db"
    clinic_tz: str = "America/New_York"
    clinic_name: str = "Riverside Family Dental"
    agent_voice: str = "alba"
    agents_api_base: str = "https://agents.assemblyai.com"
    token_expires_in_seconds: int = 300
    max_session_duration_seconds: int = 600
    # Turn on for the public demo link. Start call then requires DEMO_ACCESS_CODE.
    public_demo: bool = False
    demo_access_code: str = ""
    session_limit_per_ip: int = 30
    session_limit_global: int = 80
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3005,http://127.0.0.1:3005"
    )
    # Cloud Run sits behind Google's proxy. Local uvicorn leaves this off.
    trust_proxy: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
