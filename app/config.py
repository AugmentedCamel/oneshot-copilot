"""Configuration settings for Oneshot Copilot."""
from pydantic_settings import BaseSettings

# ============================================================================
# VERBOSE LOGGING FLAG
# Set to True to enable detailed debug logging throughout the application.
# Set to False to minimize logging output to only warnings and errors.
# ============================================================================
VERBOSE_LOGGING = True


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    SELF_URL: str
    MENTRA_URL: str
    VLM_URL: str
    RTSP_STREAM_URL: str = ""  # Optional RTSP/RTMP stream URL, empty = disabled
    STREAM_USERNAME: str = "stream_user"  # Username for stream-ingested frames
    MAX_FRAMES_PER_USER: int = 10
    
    class Config:
        env_file = ".env"


settings = Settings()