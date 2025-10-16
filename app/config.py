"""Configuration settings for Oneshot Copilot."""
from pydantic_settings import BaseSettings

# ============================================================================
# VERBOSE LOGGING FLAG
# Set to True to enable detailed debug logging throughout the application.
# Set to False to minimize logging output to only warnings and errors.
# ============================================================================
VERBOSE_LOGGING = True

# ============================================================================
# HTTP CLIENT CONFIGURATION
# Settings for the singleton httpx.AsyncClient used for VLM requests.
# ============================================================================
HTTP_TIMEOUT = 2.5  # seconds, aligned with VLM timeout
HTTP_MAX_CONNECTIONS = 20
HTTP_MAX_KEEPALIVE_CONNECTIONS = 10
HTTP_KEEPALIVE_EXPIRY = 60  # seconds

# ============================================================================
# FRAME QUEUE CONFIGURATION
# Settings for the async frame queue that decouples ingestion from processing
# ============================================================================
FRAME_QUEUE_SIZE = 10  # Maximum number of frames in queue (bounded)

# ============================================================================
# METRICS CONFIGURATION
# Settings for performance metrics collection and history
# ============================================================================
METRICS_HISTORY_SIZE = 1000  # Number of metrics to keep in memory


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