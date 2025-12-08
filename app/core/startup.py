import logging
import asyncio
from typing import List, Any
from app.config import settings
from app.domain.entities import Source
from app.services.ingest_service import ingest_service
from app.services.stream_reader import RtspStreamReader
from app.services.audio_stream_reader import AudioStreamReader
from app.services.audio_analyzer import audio_analyzer

logger = logging.getLogger(__name__)

# Keep track of active stream readers
_active_stream_readers: List[Any] = []

async def run_startup_initialization():
    """
    Initialize the application by registering default sources and starting background tasks.
    """
    logger.info("Running startup initialization...")
    
    # Log VLM Strategy mode
    logger.info(f"[STARTUP] VLM Strategy: {settings.VLM_STRATEGY} {'(async ai_node)' if settings.VLM_STRATEGY == 'reasoning' else '(sync VLM)'}")

    # Initialize Audio Analyzer models
    try:
        audio_analyzer.set_loop(asyncio.get_running_loop())
        await audio_analyzer.initialize_models()
    except Exception as e:
        logger.error(f"Failed to initialize AudioAnalyzer models: {e}")

    # 1. Register Default RTSP Source if configured
    if settings.RTSP_STREAM_URL:
        logger.info(f"Found RTSP stream configuration: {settings.RTSP_STREAM_URL}")
        
        source_id = settings.STREAM_USERNAME or "default_camera"
        
        source = Source(
            id=source_id,
            name="Default RTSP Camera",
            type="camera",
            ingest_type="rtsp",
            config={"url": settings.RTSP_STREAM_URL}
        )
        
        ingest_service.register_source(source)
        
        # Start video stream reader
        reader = RtspStreamReader(source_id, settings.RTSP_STREAM_URL)
        reader.start()
        _active_stream_readers.append(reader)
        
        # Start audio stream reader
        # Use a lambda to pass source_id to the analyzer
        audio_callback = lambda chunk: audio_analyzer.process_chunk(chunk, source_id)
        audio_reader = AudioStreamReader(source_id, settings.RTSP_STREAM_URL, audio_callback)
        audio_reader.start()
        _active_stream_readers.append(audio_reader)
        
    else:
        logger.info("No default RTSP stream configured.")

    # 2. TODO: Register Plugins (when plugin system is ready)
    # logger.info("Scanning for plugins...")
    
    logger.info("Startup initialization complete.")

async def run_shutdown_cleanup():
    """
    Cleanup resources on shutdown.
    """
    logger.info("Running shutdown cleanup...")
    
    for reader in _active_stream_readers:
        reader.stop()
    
    _active_stream_readers.clear()
    logger.info("Shutdown cleanup complete.")
