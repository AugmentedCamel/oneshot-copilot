"""Configuration settings for Oneshot Copilot."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    SELF_URL: str
    MENTRA_URL: str
    VLM_URL: str
    MAX_FRAMES_PER_USER: int = 10
    
    class Config:
        env_file = ".env"


settings = Settings()