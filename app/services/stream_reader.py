import cv2
import logging
import time
import threading
import asyncio
from typing import Optional
from app.services.ingest_service import ingest_service
from app.core.quality_control import FrameQualityAnalyzer, RateLimiter

logger = logging.getLogger(__name__)

class RtspStreamReader:
    """
    Reads frames from an RTSP stream and pushes them to the IngestService.
    Includes rate limiting (10 FPS) and quality filtering (blur/brightness).
    """

    def __init__(self, source_id: str, rtsp_url: str):
        self.source_id = source_id
        self.rtsp_url = rtsp_url
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Quality Control
        self.rate_limiter = RateLimiter(fps=10.0)
        
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
            
            # Set buffer size to minimal to avoid reading old frames
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            while self.running and not self._stop_event.is_set():
                # Rate Limiting: Check if we should process this frame slot
                if not self.rate_limiter.should_process():
                    # Sleep a tiny bit to avoid busy loop, but not too long
                    time.sleep(0.01)
                    # We still need to grab/read to clear buffer if we want latest?
                    # Actually, for RTSP, if we don't read, buffer fills.
                    # Best practice for low latency: always read, but only process if rate limit allows.
                    cap.grab() 
                    continue

                ret, frame = cap.read()
                
                if not ret:
                    logger.warning("Failed to read frame from stream, reconnecting...")
                    break
                
                # Quality Check
                is_good, reason = FrameQualityAnalyzer.is_frame_good(frame)
                if not is_good:
                    # Log occasionally or debug to avoid spam
                    # logger.debug(f"Frame skipped: {reason}")
                    continue

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
                
            cap.release()
            logger.info("Stream disconnected")
            
            if self.running:
                time.sleep(retry_interval)
