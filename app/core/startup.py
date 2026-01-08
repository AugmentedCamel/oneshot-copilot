import logging
import asyncio
from typing import List, Any
from app.config import settings
from app.domain.entities import Source
from app.services.ingest_service import ingest_service
from app.services.stream_reader import RtspStreamReader
from app.services.srt_stream_reader import SrtStreamReader
from app.services.audio_stream_reader import AudioStreamReader
from app.services.audio_analyzer import audio_analyzer


def _detect_protocol(url: str) -> str:
    """Auto-detect streaming protocol from URL prefix."""
    if url.startswith("srt://"):
        return "srt"
    elif url.startswith("rtmp://"):
        return "rtmp"
    else:
        return "rtsp"

logger = logging.getLogger(__name__)

# Keep track of active stream readers
_active_stream_readers: List[Any] = []

async def run_startup_initialization():
    """
    Initialize the application by registering default sources and starting background tasks.
    """
    logger.info("Running startup initialization...")
    logger.info(f"[STARTUP] VLM Strategy: {settings.VLM_STRATEGY}, Procedure Strategy: {settings.PROCEDURE_STRATEGY}")

    # Initialize Audio Analyzer models
    try:
        audio_analyzer.set_loop(asyncio.get_running_loop())
        await audio_analyzer.initialize_models()
    except Exception as e:
        logger.error(f"Failed to initialize AudioAnalyzer models: {e}")

    # 1. Register Default Stream Source if configured (RTSP, RTMP, or SRT)
    if settings.RTSP_STREAM_URL:
        # Auto-detect protocol from URL
        protocol = _detect_protocol(settings.RTSP_STREAM_URL)
        source_id = settings.STREAM_USERNAME or "default_camera"

        source = Source(
            id=source_id,
            name=f"Default {protocol.upper()} Camera",
            type="camera",
            ingest_type=protocol,
            config={"url": settings.RTSP_STREAM_URL}
        )
        ingest_service.register_source(source)
        logger.info(f"[STARTUP] Registered source: {source_id} ({protocol.upper()})")

        # Start video stream reader (choose based on protocol)
        if protocol == "srt":
            reader = SrtStreamReader(source_id, settings.RTSP_STREAM_URL)
            logger.info(f"[STARTUP] Using SRT stream (latency={settings.SRT_LATENCY_MS}ms)")
        else:
            reader = RtspStreamReader(source_id, settings.RTSP_STREAM_URL)
            logger.info(f"[STARTUP] Using {protocol.upper()} stream")

        reader.start()
        _active_stream_readers.append(reader)

        # Start audio stream reader (works with all protocols)
        audio_callback = lambda chunk: audio_analyzer.process_chunk(chunk, source_id)
        audio_reader = AudioStreamReader(source_id, settings.RTSP_STREAM_URL, audio_callback)
        audio_reader.start()
        _active_stream_readers.append(audio_reader)
        logger.info("[STARTUP] Video and audio stream readers started")
    else:
        logger.info("[STARTUP] No stream URL configured")

    # 2. Initialize NodeGraph service if using nodegraph strategy (must subscribe to events early!)
    if settings.PROCEDURE_STRATEGY == "nodegraph":
        from app.services.nodegraph_service import get_nodegraph_service
        get_nodegraph_service()
        logger.info("[STARTUP] NodeGraphProcedureService initialized")

    # 3. Start Data Harvester if enabled
    if settings.DATA_HARVESTER_ENABLED:
        from app.services.data_harvester import data_harvester
        logger.info("Data Harvester is enabled, starting...")
        data_harvester.start()
    else:
        logger.info("Data Harvester is disabled.")

    # 4. TODO: Register Plugins (when plugin system is ready)
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
