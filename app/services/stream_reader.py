import cv2
import logging
import time
import threading
import asyncio
from typing import Optional
from app.services.ingest_service import ingest_service

logger = logging.getLogger(__name__)

class RtspStreamReader:
    """
    Reads frames from an RTSP stream and pushes them to the IngestService.
    Replaces the legacy StreamQualityFilter.
    
    TODO: Quality filtering (blur/brightness) is NOT included in this reader.
    It should be implemented as a Job Step in the new architecture.
    """

    def __init__(self, source_id: str, rtsp_url: str):
        self.source_id = source_id
        self.rtsp_url = rtsp_url
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Capture the main event loop where the app is running
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # Fallback if initialized outside of an async context (e.g. tests)
            logger.warning("RtspStreamReader initialized outside of running event loop")
            self._main_loop = None

    def start(self):
        """Start the stream reading thread."""
        if self.running:
            return
        
        # Ensure we have a loop if not captured in init
        if not self._main_loop:
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.error("Cannot start RtspStreamReader: no running event loop found")
                return

        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Started RTSP stream reader for source {self.source_id}")

    def stop(self):
        """Stop the stream reading thread."""
        self.running = False
        self._stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info(f"Stopped RTSP stream reader for source {self.source_id}")

    def _run(self):
        """Main loop for reading frames."""
        retry_interval = 5
        
        # NOTE: We do NOT create a new event loop here. 
        # We use self._main_loop to schedule async work on the main thread.

        while self.running and not self._stop_event.is_set():
            cap = cv2.VideoCapture(self.rtsp_url)
            
            if not cap.isOpened():
                logger.error(f"Failed to open RTSP stream: {self.rtsp_url}")
                time.sleep(retry_interval)
                continue

            logger.info(f"Connected to RTSP stream: {self.rtsp_url}")
            
            while self.running and not self._stop_event.is_set():
                ret, frame = cap.read()
                
                if not ret:
                    logger.warning("Failed to read frame from stream, reconnecting...")
                    break
                
                # Encode frame to JPEG
                try:
                    _, buffer = cv2.imencode('.jpg', frame)
                    frame_bytes = buffer.tobytes()
                    
                    # Push to IngestService
                    # We run the async ingest_frame method on the MAIN loop
                    if self._main_loop and not self._main_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(
                            ingest_service.ingest_frame(self.source_id, frame_bytes),
                            self._main_loop
                        )
                    else:
                        logger.error("Main event loop is closed or missing, cannot ingest frame")
                        break
                    
                except Exception as e:
                    logger.error(f"Error processing frame: {e}")
                
                # Simple rate limiting if needed, or rely on stream FPS
                # time.sleep(0.01) 

            cap.release()
            logger.info("Stream disconnected")
            
            if self.running:
                time.sleep(retry_interval)
