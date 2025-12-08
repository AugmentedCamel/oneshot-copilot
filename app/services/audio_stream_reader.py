import asyncio
import logging
import subprocess
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class AudioStreamReader:
    def __init__(self, source_id: str, stream_url: str, callback: Callable[[bytes], None]):
        self.source_id = source_id
        self.stream_url = stream_url
        self.callback = callback
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run_ffmpeg, daemon=True)
        self.thread.start()
        logger.info(f"AudioStreamReader started for {self.source_id}")

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.thread:
            self.thread.join(timeout=2)
        logger.info(f"AudioStreamReader stopped for {self.source_id}")

    def _run_ffmpeg(self):
        # FFmpeg command to extract audio:
        # -i [url]: Input URL
        # -vn: Disable video
        # -f s16le: Output format signed 16-bit little endian
        # -acodec pcm_s16le: Audio codec
        # -ar 16000: Sample rate 16kHz
        # -ac 1: Channels 1 (mono)
        # -: Output to stdout
        command = [
            "ffmpeg",
            "-i", self.stream_url,
            "-vn",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-"
        ]

        while self.running and not self._stop_event.is_set():
            try:
                logger.info(f"Starting FFmpeg for audio extraction: {self.stream_url}")
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, # Suppress stderr to avoid log spam, or redirect to log if needed
                    bufsize=1024 * 10 # Buffer size
                )

                chunk_size = 640 # 20ms at 16kHz, 16-bit mono (16000 * 0.02 * 2 bytes)
                
                while self.running and self.process.poll() is None:
                    if self._stop_event.is_set():
                        break
                    
                    # Read raw audio chunk
                    if self.process.stdout:
                        chunk = self.process.stdout.read(chunk_size)
                        if not chunk:
                            break
                        
                        # Pass chunk to callback
                        # The callback is expected to be thread-safe or handle its own concurrency
                        try:
                            self.callback(chunk)
                        except Exception as e:
                            logger.error(f"Error in audio callback: {e}")
                
                if self.process.returncode is not None and self.process.returncode != 0:
                     logger.warning(f"FFmpeg exited with code {self.process.returncode}")

            except Exception as e:
                logger.error(f"Error in AudioStreamReader: {e}")
            
            finally:
                if self.process:
                    self.process.terminate()
                    self.process = None

            if self.running and not self._stop_event.is_set():
                logger.info("FFmpeg stream ended or failed. Reconnecting in 5 seconds...")
                asyncio.run(asyncio.sleep(5)) # This is a blocking call in a thread, so time.sleep is better or asyncio.run
                import time
                time.sleep(5)
