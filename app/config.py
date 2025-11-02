"""Configuration settings for Oneshot Copilot."""
from pydantic_settings import BaseSettings

# ============================================================================
# VERBOSE LOGGING FLAG
# Set to True to enable detailed debug logging throughout the application.
# Set to False to minimize logging output to only warnings and errors.
# ============================================================================
VERBOSE_LOGGING = False

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

# ============================================================================
# FRAME STORAGE CONFIGURATION
# Settings for saving frames to disk for debugging/verification
# ============================================================================
SAVE_FRAMES_TO_DISK = False  # Set to True to save all frames to disk
FRAMES_DIRECTORY = "app/data/frames"  # Directory to save frames


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    SELF_URL: str
    MENTRA_URL: str
    
    # VLM Provider Configuration
    VLM_PROVIDER: str = "local"  # Options: "local", "moondream", "auki_local"
    VLM_URL: str = ""  # Used by: local, auki_local
    MOONDREAM_API_KEY: str = ""  # Used by: moondream
    
    RTSP_STREAM_URL: str = ""  # Optional RTSP/RTMP stream URL, empty = disabled
    STREAM_USERNAME: str = "stream_user"  # Username for stream-ingested frames
    MAX_FRAMES_PER_USER: int = 10
    SAVE_FRAMES_TO_DISK: bool = False  # Save frames to disk for debugging/verification
    
    class Config:
        env_file = ".env"


settings = Settings()