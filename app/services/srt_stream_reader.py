"""
SRT Stream Reader - FFmpeg-based video frame capture for SRT streams.

Uses FFmpeg subprocess for better SRT protocol support compared to OpenCV.
Handles automatic reconnection, rate limiting, and quality filtering.
"""
import cv2
import json
import logging
import numpy as np
import subprocess
import threading
import time
import asyncio
from typing import Optional, Tuple

from app.config import settings
from app.services.ingest_service import ingest_service
from app.core.quality_control import FrameQualityAnalyzer, RateLimiter

logger = logging.getLogger(__name__)


def probe_stream_info(stream_url: str, timeout: int = 10) -> Tuple[int, int, float]:
    """
    Probe stream to get resolution and frame rate using ffprobe.

    Args:
        stream_url: The SRT stream URL
        timeout: Probe timeout in seconds

    Returns:
        Tuple of (width, height, fps)

    Raises:
        RuntimeError: If probe fails or returns invalid data
    """
    command = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json",
        stream_url
    ]

    try:
        logger.info(f"Probing stream: {stream_url}")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)

        if not data.get("streams"):
            raise RuntimeError("No video streams found")

        stream = data["streams"][0]
        width = stream.get("width")
        height = stream.get("height")
        fps_str = stream.get("r_frame_rate", "30/1")

        if not width or not height:
            raise RuntimeError(f"Invalid resolution: {width}x{height}")

        # Parse frame rate (format: "30/1" or "30000/1001")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)

        logger.info(f"Stream info: {width}x{height} @ {fps:.2f} fps")
        return width, height, fps

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Stream probe timed out after {timeout}s")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe output: {e}")


class SrtStreamReader:
    """
    Reads frames from an SRT stream using FFmpeg subprocess.

    Features:
    - Auto-detects resolution and fps via ffprobe
    - Low-latency FFmpeg flags for SRT
    - Rate limiting (20 FPS default)
    - Quality filtering (blur/brightness)
    - Automatic reconnection on failure
    """

    def __init__(self, source_id: str, srt_url: str):
        self.source_id = source_id
        self.srt_url = srt_url
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.process: Optional[subprocess.Popen] = None

        # Stream info (populated by probe)
        self.width: Optional[int] = None
        self.height: Optional[int] = None
        self.fps: Optional[float] = None
        self.frame_size: Optional[int] = None  # bytes per frame

        # Quality Control
        self.rate_limiter = RateLimiter(fps=20.0)

        # Timing instrumentation
        self._frame_count = 0
        self._fps_start_time = time.time()
        self._last_frame_time = 0.0

        # Capture the main event loop
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("SrtStreamReader initialized outside of running event loop")
            self._main_loop = None

    def start(self):
        """Start the stream reading thread."""
        if self.running:
            return

        if not self._main_loop:
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.error("Cannot start SrtStreamReader: no running event loop found")
                return

        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Started SRT stream reader for source {self.source_id}")

    def stop(self):
        """Stop the stream reading thread."""
        self.running = False
        self._stop_event.set()

        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

        if self.thread:
            self.thread.join(timeout=2.0)

        logger.info(f"Stopped SRT stream reader for source {self.source_id}")

    def _probe_stream(self) -> bool:
        """Probe stream to get resolution. Returns True on success."""
        try:
            self.width, self.height, self.fps = probe_stream_info(self.srt_url)
            self.frame_size = self.width * self.height * 3  # BGR24 = 3 bytes per pixel
            return True
        except RuntimeError as e:
            logger.error(f"Failed to probe stream: {e}")
            return False

    def _build_ffmpeg_command(self) -> list:
        """Build FFmpeg command for low-latency SRT reading."""
        return [
            "ffmpeg",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-i", self.srt_url,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-an",  # No audio (handled separately)
            "-"
        ]

    def _run(self):
        """Main loop for reading frames from FFmpeg."""
        retry_interval = 5

        logger.info(f"[SRT_DEBUG] Starting SRT reader loop for source_id={self.source_id}")
        logger.info(f"[SRT_DEBUG] SRT URL: {self.srt_url}")

        while self.running and not self._stop_event.is_set():
            # Probe stream to get resolution
            logger.info(f"[SRT_DEBUG] Probing stream...")
            if not self._probe_stream():
                logger.warning(f"[SRT_DEBUG] Stream probe failed, retrying in {retry_interval}s...")
                time.sleep(retry_interval)
                continue

            logger.info(f"[SRT_DEBUG] Probe successful: {self.width}x{self.height}, frame_size={self.frame_size} bytes")

            # Start FFmpeg process
            command = self._build_ffmpeg_command()
            logger.info(f"[SRT_DEBUG] Starting FFmpeg: {' '.join(command)}")

            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,  # Capture stderr for debugging
                    bufsize=self.frame_size * 2  # Buffer 2 frames
                )
                logger.info(f"[SRT_DEBUG] FFmpeg process started, PID={self.process.pid}")
            except Exception as e:
                logger.error(f"[SRT_DEBUG] Failed to start FFmpeg: {e}")
                time.sleep(retry_interval)
                continue

            logger.info(f"[SRT_DEBUG] Connected to SRT stream: {self.srt_url}")

            # Reset counters
            self._frame_count = 0
            self._fps_start_time = time.time()
            self._last_frame_time = time.time()
            _quality_rejected = 0
            _frames_read = 0

            # Read frames from FFmpeg stdout
            while self.running and not self._stop_event.is_set():
                # Check if process is still alive
                if self.process.poll() is not None:
                    stderr_output = self.process.stderr.read().decode() if self.process.stderr else ""
                    logger.warning(f"[SRT_DEBUG] FFmpeg process terminated, exit code={self.process.returncode}")
                    if stderr_output:
                        logger.warning(f"[SRT_DEBUG] FFmpeg stderr: {stderr_output[:500]}")
                    break

                # Rate limiting
                if not self.rate_limiter.should_process():
                    # Skip frame but still read to clear buffer
                    try:
                        if self.process.stdout:
                            self.process.stdout.read(self.frame_size)
                    except:
                        pass
                    time.sleep(0.01)
                    continue

                # Read raw frame bytes
                try:
                    if not self.process.stdout:
                        logger.error("[SRT_DEBUG] No stdout pipe!")
                        break

                    raw_bytes = self.process.stdout.read(self.frame_size)
                    _frames_read += 1

                    if not raw_bytes:
                        logger.warning(f"[SRT_DEBUG] No bytes received (frames_read={_frames_read})")
                        break

                    if len(raw_bytes) < self.frame_size:
                        logger.warning(f"[SRT_DEBUG] Incomplete frame: got {len(raw_bytes)}, expected {self.frame_size}")
                        break

                    # Convert to numpy array
                    frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(
                        (self.height, self.width, 3)
                    )

                    # Quality check
                    is_good, reason = FrameQualityAnalyzer.is_frame_good(frame)
                    if not is_good:
                        _quality_rejected += 1
                        if _quality_rejected % 10 == 1:
                            logger.info(f"[SRT_DEBUG] Frame rejected by quality filter: {reason} (total rejected={_quality_rejected})")
                        continue

                    # Encode to JPEG
                    encode_start = time.time()
                    _, buffer = cv2.imencode('.jpg', frame)
                    frame_bytes = buffer.tobytes()
                    encode_ms = (time.time() - encode_start) * 1000

                    # Track timing
                    now = time.time()
                    frame_interval_ms = (now - self._last_frame_time) * 1000
                    self._last_frame_time = now
                    self._frame_count += 1

                    # Log every frame for debugging
                    logger.info(
                        f"[SRT_DEBUG] Frame #{self._frame_count} captured: "
                        f"interval={frame_interval_ms:.0f}ms, encode={encode_ms:.1f}ms, "
                        f"size={len(frame_bytes)} bytes, source_id={self.source_id}"
                    )

                    # Push to IngestService
                    if self._main_loop and not self._main_loop.is_closed():
                        logger.info(f"[SRT_DEBUG] Pushing frame #{self._frame_count} to IngestService...")
                        asyncio.run_coroutine_threadsafe(
                            ingest_service.ingest_frame(self.source_id, frame_bytes),
                            self._main_loop
                        )
                        logger.info(f"[SRT_DEBUG] Frame #{self._frame_count} pushed to IngestService")
                    else:
                        logger.error("[SRT_DEBUG] Main event loop is closed or missing!")
                        break

                except Exception as e:
                    logger.error(f"[SRT_DEBUG] Error processing frame: {e}", exc_info=True)
                    break

            # Cleanup process
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                self.process = None

            logger.info("SRT stream disconnected")

            if self.running and not self._stop_event.is_set():
                logger.info(f"Reconnecting in {retry_interval}s...")
                time.sleep(retry_interval)
