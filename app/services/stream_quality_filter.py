#!/usr/bin/env python3
"""
Stream Quality Filter
Reads RTSP stream, filters frames by quality (blur/brightness), and outputs to both new stream and file.
Maintains low latency with original timestamps.
"""

import cv2
import numpy as np
import subprocess
import argparse
import logging
import sys
import threading
import time
from queue import Queue, Empty
from typing import Optional, Tuple, Dict
from datetime import datetime
import os
import requests
from io import BytesIO

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FrameQualityAnalyzer:
    """
    Analyzes frame quality based on blur and brightness metrics.
    """

    @staticmethod
    def calculate_blur_score(frame: np.ndarray) -> float:
        """
        Calculate blur score using Laplacian variance.
        Higher values = sharper image.

        Args:
            frame: Input frame (BGR or grayscale)

        Returns:
            Blur score (variance of Laplacian)
        """
        # Convert to grayscale if needed
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Calculate Laplacian variance
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = laplacian.var()

        return variance

    @staticmethod
    def calculate_brightness(frame: np.ndarray) -> float:
        """
        Calculate average brightness of frame.

        Args:
            frame: Input frame (BGR)

        Returns:
            Average brightness (0-255)
        """
        # Convert to grayscale
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        return np.mean(gray)

    @staticmethod
    def analyze_frame(
            frame: np.ndarray,
            blur_threshold: float = 100.0,
            brightness_min: float = 50.0,
            brightness_max: float = 250.0
    ) -> Tuple[bool, Dict]:
        """
        Analyze frame quality and determine if it should be kept.

        Args:
            frame: Input frame
            blur_threshold: Minimum blur score (higher = sharper required)
            brightness_min: Minimum brightness (0-255)
            brightness_max: Maximum brightness (0-255)

        Returns:
            Tuple of (should_keep, metrics_dict)
        """
        blur_score = FrameQualityAnalyzer.calculate_blur_score(frame)
        brightness = FrameQualityAnalyzer.calculate_brightness(frame)

        should_keep = (
                blur_score >= blur_threshold and
                brightness >= brightness_min and
                brightness <= brightness_max
        )

        metrics = {
            'blur_score': blur_score,
            'brightness': brightness,
            'should_keep': should_keep,
            'blur_passed': blur_score >= blur_threshold,
            'brightness_passed': brightness_min <= brightness <= brightness_max
        }

        return should_keep, metrics


class StreamQualityFilter:
    """
    Filters RTSP stream by quality and outputs to new stream + file.
    Preserves timestamps for low latency.
    """

    def __init__(
            self,
            input_rtsp_url: str,
            output_rtsp_url: Optional[str] = None,
            output_file: Optional[str] = None,
            blur_threshold: float = 100.0,
            brightness_min: float = 50.0,
            brightness_max: float = 250.0,
            buffer_size: int = 30,
            show_preview: bool = False,
            post_url: Optional[str] = None,
            post_question: str = "What do you see in this image?",
            post_verify_ssl: bool = False,
            post_timeout: int = 10,
            post_jpg_quality: int = 95,
            min_frame_interval: float = 0.0,
            post_rotate_90: bool = False,
            save_latest_frame: Optional[str] = None,
            low_latency_mode: bool = False,
            target_resolution: Optional[Tuple[int, int]] = None,
            post_username: Optional[str] = None
    ):
        """
        Initialize the stream quality filter.

        Args:
            input_rtsp_url: Source RTSP stream URL
            output_rtsp_url: Destination RTSP stream URL (optional)
            output_file: Path to output video file (optional)
            blur_threshold: Minimum blur score for acceptable frames
            brightness_min: Minimum brightness for acceptable frames
            brightness_max: Maximum brightness for acceptable frames
            buffer_size: Frame buffer size
            show_preview: Show preview window with quality metrics
            post_url: Optional URL to POST filtered frames to
            post_question: Question string to send with each frame
            post_verify_ssl: Whether to verify SSL certificates for POST requests
            post_timeout: Timeout for POST requests in seconds
            post_jpg_quality: JPEG quality for posted frames (0-100)
            min_frame_interval: Minimum time interval (in seconds) between selected frames (0 = disabled)
            post_rotate_90: Rotate frames 90 degrees clockwise before POSTing (for POST only)
            save_latest_frame: Path to save the latest processed frame (updated continuously)
            low_latency_mode: Enable aggressive buffer flushing for minimal latency (may skip frames)
            target_resolution: Target resolution (width, height) to resize frames before POSTing (None = no resize)
            post_username: Username to use when POSTing frames (if None, uses stream_id extracted from URL)
        """
        self.input_rtsp_url = input_rtsp_url
        self.output_rtsp_url = output_rtsp_url
        self.output_file = output_file
        self.blur_threshold = blur_threshold
        self.brightness_min = brightness_min
        self.brightness_max = brightness_max
        self.buffer_size = buffer_size
        self.show_preview = show_preview
        self.min_frame_interval = min_frame_interval

        # POST configuration
        self.post_url = post_url
        self.post_question = post_question
        self.post_verify_ssl = post_verify_ssl
        self.post_timeout = post_timeout
        self.post_jpg_quality = post_jpg_quality
        self.post_rotate_90 = post_rotate_90
        self.save_latest_frame = save_latest_frame
        self.low_latency_mode = low_latency_mode
        self.target_resolution = target_resolution

        # Extract stream ID from RTSP URL for username field
        # e.g., rtsp://192.168.9.21:8554/live/str -> "str"
        self.stream_id = input_rtsp_url.rstrip('/').split('/')[-1] if input_rtsp_url else "unknown"
        
        # Use provided username or fall back to stream_id
        self.post_username = post_username if post_username else self.stream_id

        if not output_rtsp_url and not output_file and not post_url:
            raise ValueError("Must specify at least one output: output_rtsp_url, output_file, or post_url")

        self.frame_queue = Queue(maxsize=buffer_size)
        self.post_queue = Queue(maxsize=buffer_size) if post_url else None
        self.running = False
        self.stats = {
            'frames_read': 0,
            'frames_kept': 0,
            'frames_rejected': 0,
            'frames_too_blurry': 0,
            'frames_too_dark': 0,
            'frames_too_bright': 0,
            'frames_dropped_interval': 0,
            'frames_dropped_waiting_post': 0,
            'frames_written': 0,
            'frames_posted': 0,
            'post_successes': 0,
            'post_failures': 0,
        }

        # Timing statistics (cumulative times in seconds)
        self.timing_stats = {
            'frame_capture': 0.0,
            'quality_analysis': 0.0,
            'frame_rotation': 0.0,
            'frame_resize': 0.0,
            'frame_save': 0.0,
            'jpg_encoding': 0.0,
            'post_request': 0.0,
            'frame_write': 0.0,
        }
        self.timing_counts = {
            'frame_capture': 0,
            'quality_analysis': 0,
            'frame_rotation': 0,
            'frame_resize': 0,
            'frame_save': 0,
            'jpg_encoding': 0,
            'post_request': 0,
            'frame_write': 0,
        }

        self.start_time = None
        self.last_kept_frame_time = None

        # POST state tracking
        self.waiting_for_post_response = False
        self.post_lock = threading.Lock()

        self.cap = None
        self.ffmpeg_process = None
        self.video_writer = None
        self.input_fps = 30  # Default, will be updated

    @staticmethod
    def frame_to_jpg_bytes(frame: np.ndarray, quality: int = 95) -> bytes:
        """
        Convert frame to JPG format bytes.

        Args:
            frame: Input frame (BGR format)
            quality: JPEG quality (0-100, higher = better quality)

        Returns:
            JPG image as bytes
        """
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        success, encoded_image = cv2.imencode('.jpg', frame, encode_param)

        if not success:
            raise RuntimeError("Failed to encode frame to JPG")

        return encoded_image.tobytes()

    @staticmethod
    def post_frame_with_question(
            url: str,
            frame: np.ndarray,
            question: str,
            jpg_quality: int = 95,
            timeout: int = 10,
            verify_ssl: bool = False
    ) -> requests.Response:
        """
        POST frame image and question to a given URL using multipart/form-data.

        Args:
            url: Target URL for POST request
            frame: Input frame (BGR format)
            question: Question string to send
            jpg_quality: JPEG quality (0-100)
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates

        Returns:
            requests.Response object

        Raises:
            requests.RequestException: If request fails
        """
        # Convert frame to JPG bytes
        jpg_bytes = StreamQualityFilter.frame_to_jpg_bytes(frame, jpg_quality)

        # Prepare multipart form data
        files = {
            'file': ('frame.jpg', BytesIO(jpg_bytes), 'image/jpeg')
        }
        data = {
            'question': question,
            'webhook_url': 'http://192.168.9.200:3000/api/feedback'
        }

        # Make POST request
        response = requests.post(
            url,
            files=files,
            data=data,
            timeout=timeout,
            verify=verify_ssl
        )

        return response

    def start_ffmpeg_streamer(self, width: int, height: int, fps: float):
        """
        Start ffmpeg process for RTSP streaming with low latency settings.

        Args:
            width: Frame width
            height: Frame height
            fps: Frames per second
        """
        ffmpeg_cmd = [
            'ffmpeg',
            '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{width}x{height}',
            '-r', str(fps),
            '-i', '-',  # Read from stdin
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-g', str(int(fps)),  # Keyframe interval = 1 second
            '-b:v', '2000k',
            '-maxrate', '2000k',
            '-bufsize', '4000k',
            '-pix_fmt', 'yuv420p',
            '-f', 'rtsp',
            '-rtsp_transport', 'tcp',
            self.output_rtsp_url
        ]

        logger.info(f"Starting ffmpeg RTSP streamer to {self.output_rtsp_url}")

        self.ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Start thread to monitor ffmpeg stderr
        def read_stderr():
            while self.running:
                line = self.ffmpeg_process.stderr.readline()
                if line:
                    logger.debug(f"ffmpeg: {line.decode().strip()}")

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

    def start_file_writer(self, width: int, height: int, fps: float):
        """
        Start video file writer with H.264 codec.

        Args:
            width: Frame width
            height: Frame height
            fps: Frames per second
        """
        # Ensure output directory exists
        output_dir = os.path.dirname(self.output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Use H.264 codec for good compression and compatibility
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(
            self.output_file,
            fourcc,
            fps,
            (width, height)
        )

        if not self.video_writer.isOpened():
            raise RuntimeError(f"Failed to create video writer for {self.output_file}")

        logger.info(f"Writing filtered frames to file: {self.output_file}")

    def capture_and_filter_frames(self):
        """
        Capture frames from input RTSP stream and filter by quality.
        """
        logger.info(f"Connecting to input RTSP stream: {self.input_rtsp_url}")

        # Use TCP for more reliable connection (UDP can cause frame drops)
        # Set minimal buffering for low latency
        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|buffer_size;0'
        self.cap = cv2.VideoCapture(self.input_rtsp_url, cv2.CAP_FFMPEG)

        # Set buffer size to 1 to minimize latency (discard old frames)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not self.cap.isOpened():
            logger.error("Failed to open input RTSP stream")
            self.running = False
            return

        # Get stream properties
        self.input_fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self.input_fps == 0 or self.input_fps > 120:  # Invalid FPS
            self.input_fps = 30
            logger.warning(f"Invalid FPS detected, using default: {self.input_fps}")

        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        logger.info(f"Input stream: {width}x{height} @ {self.input_fps} FPS")
        logger.info(
            f"Quality thresholds - Blur: {self.blur_threshold}, Brightness: {self.brightness_min}-{self.brightness_max}")
        if self.min_frame_interval > 0:
            logger.info(f"Minimum frame interval: {self.min_frame_interval:.2f}s")
        if self.low_latency_mode:
            logger.info("⚡ Low latency mode ENABLED - aggressively flushing buffers")

        last_log_time = time.time()
        frame_times = []  # Track timestamps for maintaining timing
        frames_since_log = 0
        last_successful_frame_time = time.time()  # Track last successful frame read
        frame_timeout = 3.0  # Stop if no frames for 3 seconds

        while self.running:
            # Check timeout at the start of the loop before attempting to read
            time_since_last_frame = time.time() - last_successful_frame_time
            if time_since_last_frame > frame_timeout:
                logger.error(f"No frames received for {time_since_last_frame:.1f} seconds (timeout: {frame_timeout}s). Stopping service gracefully.")
                self.running = False
                break
            
            frame_start = time.time()

            # Low latency mode: Always flush buffer to get the latest frame
            if self.low_latency_mode:
                # Aggressively flush buffer by grabbing (not reading) multiple frames
                for _ in range(5):
                    self.cap.grab()
            else:
                # Normal mode: Only flush if queues are building up
                if self.frame_queue.qsize() > 5 or (self.post_queue and self.post_queue.qsize() > 2):
                    logger.debug(
                        f"Flushing buffer - Queue sizes: frame={self.frame_queue.qsize()}, post={self.post_queue.qsize() if self.post_queue else 0}")
                    # Grab latest frame by reading multiple times quickly
                    for _ in range(3):
                        self.cap.grab()

            # Time frame capture
            capture_start = time.time()
            ret, frame = self.cap.read()
            capture_time = time.time() - capture_start
            frames_since_log += 1

            if not ret:
                time_since_last_frame = time.time() - last_successful_frame_time
                logger.warning(f"Failed to read frame from input stream (no frames for {time_since_last_frame:.1f}s)")
                time.sleep(0.1)
                continue

            # Update last successful frame time
            last_successful_frame_time = time.time()
            
            self.stats['frames_read'] += 1
            self.timing_stats['frame_capture'] += capture_time
            self.timing_counts['frame_capture'] += 1

            # Time quality analysis
            analysis_start = time.time()
            should_keep, metrics = FrameQualityAnalyzer.analyze_frame(
                frame,
                self.blur_threshold,
                self.brightness_min,
                self.brightness_max
            )
            analysis_time = time.time() - analysis_start
            self.timing_stats['quality_analysis'] += analysis_time
            self.timing_counts['quality_analysis'] += 1

            # Check minimum frame interval if enabled
            current_time = time.time()
            interval_check_passed = True
            post_waiting_check_passed = True

            if should_keep and self.min_frame_interval > 0:
                if self.last_kept_frame_time is not None:
                    time_since_last = current_time - self.last_kept_frame_time
                    if time_since_last < self.min_frame_interval:
                        interval_check_passed = False
                        should_keep = False
                        self.stats['frames_dropped_interval'] += 1

            # Check if waiting for POST response (only if POST is enabled)
            if should_keep and self.post_url:
                with self.post_lock:
                    if self.waiting_for_post_response:
                        post_waiting_check_passed = False
                        should_keep = False
                        self.stats['frames_dropped_waiting_post'] += 1

            if should_keep:
                self.stats['frames_kept'] += 1
                self.last_kept_frame_time = current_time

                # Add frame with timestamp to queue
                try:
                    self.frame_queue.put((frame, current_time), block=False)
                except:
                    # Queue is full, skip this frame
                    logger.debug("Frame queue full, skipping frame")
                    pass

                # Add frame to POST queue if enabled
                if self.post_queue is not None:
                    try:
                        self.post_queue.put(frame.copy(), block=False)
                    except:
                        # Queue is full, skip this frame
                        logger.debug("POST queue full, skipping frame")
                        pass
            else:
                # Only count as rejected if quality check failed (not interval or POST waiting)
                if not interval_check_passed or not post_waiting_check_passed:
                    # Frame dropped due to interval or POST waiting, already counted above
                    pass
                else:
                    self.stats['frames_rejected'] += 1

                    # Track specific rejection reasons
                    if not metrics['blur_passed']:
                        self.stats['frames_too_blurry'] += 1
                    if not metrics['brightness_passed']:
                        if metrics['brightness'] < self.brightness_min:
                            self.stats['frames_too_dark'] += 1
                        else:
                            self.stats['frames_too_bright'] += 1

            # Show preview if enabled
            if self.show_preview:
                self._show_preview(frame, metrics)

            # Log stats every 5 seconds
            if time.time() - last_log_time > 5.0:
                self._log_stats()
                # Log queue status for latency diagnosis
                logger.info(
                    f"Latency Info - Frames/sec: {frames_since_log / 5.0:.1f}, "
                    f"Frame Queue: {self.frame_queue.qsize()}/{self.buffer_size}, "
                    f"POST Queue: {self.post_queue.qsize()}/{self.buffer_size if self.post_queue else 0}"
                )
                frames_since_log = 0
                last_log_time = time.time()

            # Maintain approximate input frame rate
            frame_time = time.time() - frame_start
            expected_frame_time = 1.0 / self.input_fps
            if frame_time < expected_frame_time:
                time.sleep(expected_frame_time - frame_time)

        self.cap.release()
        if self.show_preview:
            cv2.destroyAllWindows()

    def write_frames(self):
        """
        Write filtered frames to output destinations (RTSP stream and/or file).
        If no file/stream output is configured (POST-only mode), just consume the queue.
        """
        # If POST-only mode, just wait without doing anything
        if not self.output_rtsp_url and not self.output_file:
            logger.info("No file/stream output configured, only POST mode")
            while self.running:
                try:
                    # Just consume the queue to prevent it from filling up
                    self.frame_queue.get(timeout=1.0)
                except Empty:
                    pass
            return

        # Wait for first frame to get dimensions
        logger.info("Waiting for first quality frame...")

        first_frame, first_timestamp = self.frame_queue.get()
        height, width = first_frame.shape[:2]

        # Initialize outputs
        if self.output_rtsp_url:
            self.start_ffmpeg_streamer(width, height, self.input_fps)

        if self.output_file:
            self.start_file_writer(width, height, self.input_fps)

        logger.info(f"Output dimensions: {width}x{height} @ {self.input_fps} FPS")
        logger.info("Started writing filtered frames")

        last_frame_time = first_timestamp

        while self.running:
            try:
                frame, timestamp = self.frame_queue.get(timeout=1.0)

                # Time frame writing
                write_start = time.time()

                # Write to RTSP stream
                if self.ffmpeg_process:
                    try:
                        self.ffmpeg_process.stdin.write(frame.tobytes())
                    except BrokenPipeError:
                        logger.error("ffmpeg process pipe broken")
                        self.output_rtsp_url = None  # Disable RTSP output
                        self.ffmpeg_process = None

                # Write to file
                if self.video_writer:
                    self.video_writer.write(frame)

                # Save latest frame to disk if configured and POST is not enabled
                # (if POST is enabled, saving happens in POST thread after rotation)
                if self.save_latest_frame and not self.post_url:
                    try:
                        save_start = time.time()
                        cv2.imwrite(self.save_latest_frame, frame)
                        save_time = time.time() - save_start
                        self.timing_stats['frame_save'] += save_time
                        self.timing_counts['frame_save'] += 1
                    except Exception as e:
                        logger.warning(f"Failed to save latest frame: {e}")

                write_time = time.time() - write_start
                self.timing_stats['frame_write'] += write_time
                self.timing_counts['frame_write'] += 1

                self.stats['frames_written'] += 1

                # Maintain timing based on original timestamps
                time_since_last = timestamp - last_frame_time
                if time_since_last > 0:
                    time.sleep(min(time_since_last, 1.0 / self.input_fps))

                last_frame_time = timestamp

            except Empty:
                # No frame available, continue waiting
                pass
            except Exception as e:
                logger.error(f"Error writing frame: {e}", exc_info=True)

    def post_frames(self):
        """
        POST filtered frames to API endpoint in a separate thread.
        """
        if not self.post_url:
            return

        logger.info(f"Starting POST thread to {self.post_url}")
        logger.info(f"Question: {self.post_question}")
        logger.info(f"Stream ID: {self.stream_id}, Username: {self.post_username}")
        if self.post_rotate_90:
            logger.info("Rotation: 90 degrees counterclockwise enabled for POST")
        if self.target_resolution:
            logger.info(f"Target resolution: {self.target_resolution[0]}x{self.target_resolution[1]}")

        while self.running:
            try:
                frame = self.post_queue.get(timeout=1.0)

                self.stats['frames_posted'] += 1

                # Time rotation if requested (for POST only)
                if self.post_rotate_90:
                    rotation_start = time.time()
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    rotation_time = time.time() - rotation_start
                    self.timing_stats['frame_rotation'] += rotation_time
                    self.timing_counts['frame_rotation'] += 1

                # Resize frame if target resolution is specified
                if self.target_resolution:
                    resize_start = time.time()
                    target_width, target_height = self.target_resolution
                    # Use INTER_AREA for best quality when downscaling (fastest and best results)
                    frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
                    resize_time = time.time() - resize_start
                    self.timing_stats['frame_resize'] += resize_time
                    self.timing_counts['frame_resize'] += 1

                # Save latest frame to disk if configured
                if self.save_latest_frame:
                    try:
                        save_start = time.time()
                        cv2.imwrite(self.save_latest_frame, frame)
                        save_time = time.time() - save_start
                        self.timing_stats['frame_save'] += save_time
                        self.timing_counts['frame_save'] += 1
                    except Exception as e:
                        logger.warning(f"Failed to save latest frame: {e}")

                # Set flag to indicate we're waiting for POST response
                with self.post_lock:
                    self.waiting_for_post_response = True

                # POST the frame
                try:
                    # Time JPG encoding
                    encoding_start = time.time()
                    jpg_bytes = self.frame_to_jpg_bytes(frame, self.post_jpg_quality)
                    encoding_time = time.time() - encoding_start
                    self.timing_stats['jpg_encoding'] += encoding_time
                    self.timing_counts['jpg_encoding'] += 1

                    # Time POST request
                    post_start = time.time()

                    # Generate frame_id as current timestamp in milliseconds
                    frame_id = int(time.time() * 1000)

                    files = {
                        'file': ('frame.jpg', BytesIO(jpg_bytes), 'image/jpeg')
                    }
                    data = {
                        'question': self.post_question,
                        'webhook_url': 'http://192.168.9.200:3000/api/feedback',
                        'username': self.post_username,
                        'frame_id': str(frame_id)
                    }
                    response = requests.post(
                        self.post_url,
                        files=files,
                        data=data,
                        timeout=self.post_timeout,
                        verify=self.post_verify_ssl
                    )
                    post_time = time.time() - post_start
                    post_time_ms = post_time * 1000  # Convert to milliseconds
                    self.timing_stats['post_request'] += post_time
                    self.timing_counts['post_request'] += 1

                    self.stats['post_successes'] += 1
                    
                    # Log structured metrics for stream ingestion
                    logger.info(
                        f"STREAM_POST_METRICS user={self.post_username} "
                        f"frame_id={frame_id} "
                        f"post_time_ms={post_time_ms:.1f} "
                        f"status={response.status_code}"
                    )
                    
                    logger.debug(
                        f"POST successful: {response.status_code} - frame_id: {frame_id} - {response.text[:100]}")

                except requests.exceptions.Timeout:
                    self.stats['post_failures'] += 1
                    logger.warning(f"POST request timed out after {self.post_timeout}s")

                except requests.exceptions.RequestException as e:
                    self.stats['post_failures'] += 1
                    logger.warning(f"POST request failed: {e}")

                except Exception as e:
                    self.stats['post_failures'] += 1
                    logger.error(f"Unexpected error during POST: {e}", exc_info=True)

                finally:
                    # Clear flag after POST completes (success or failure)
                    with self.post_lock:
                        self.waiting_for_post_response = False

            except Empty:
                # No frame available, continue waiting
                pass
            except Exception as e:
                logger.error(f"Error in POST thread: {e}", exc_info=True)

        logger.info("POST thread stopped")

    def _show_preview(self, frame: np.ndarray, metrics: Dict):
        """
        Show preview window with quality metrics overlay.

        Args:
            frame: Frame to display
            metrics: Quality metrics
        """
        display_frame = frame.copy()
        h, w = display_frame.shape[:2]

        # Add metrics overlay
        status_text = "KEEP" if metrics['should_keep'] else "REJECT"
        status_color = (0, 255, 0) if metrics['should_keep'] else (0, 0, 255)

        cv2.putText(display_frame, status_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2)
        cv2.putText(display_frame, f"Blur: {metrics['blur_score']:.1f}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(display_frame, f"Bright: {metrics['brightness']:.1f}", (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        # Resize if too large
        max_display_height = 720
        if h > max_display_height:
            scale = max_display_height / h
            new_w = int(w * scale)
            display_frame = cv2.resize(display_frame, (new_w, max_display_height))

        cv2.imshow('Stream Quality Filter', display_frame)
        cv2.waitKey(1)

    def _log_stats(self):
        """Log current statistics."""
        total_read = self.stats['frames_read']
        kept = self.stats['frames_kept']
        rejected = self.stats['frames_rejected']
        written = self.stats['frames_written']

        if total_read > 0:
            keep_rate = (kept / total_read) * 100
            reject_rate = (rejected / total_read) * 100
        else:
            keep_rate = reject_rate = 0

        elapsed = time.time() - self.start_time if self.start_time else 0
        fps = total_read / elapsed if elapsed > 0 else 0

        logger.info(
            f"Stats - Read: {total_read} ({fps:.1f} fps), "
            f"Kept: {kept} ({keep_rate:.1f}%), Rejected: {rejected} ({reject_rate:.1f}%), "
            f"Written: {written}, Queue: {self.frame_queue.qsize()}"
        )
        logger.info(
            f"Rejection details - Blurry: {self.stats['frames_too_blurry']}, "
            f"Dark: {self.stats['frames_too_dark']}, Bright: {self.stats['frames_too_bright']}, "
            f"Interval: {self.stats['frames_dropped_interval']}, "
            f"Waiting POST: {self.stats['frames_dropped_waiting_post']}"
        )

        # Log POST stats if enabled
        if self.post_url:
            posted = self.stats['frames_posted']
            successes = self.stats['post_successes']
            failures = self.stats['post_failures']
            success_rate = (successes / posted * 100) if posted > 0 else 0
            logger.info(
                f"POST stats - Posted: {posted}, Success: {successes} ({success_rate:.1f}%), "
                f"Failed: {failures}, Queue: {self.post_queue.qsize() if self.post_queue else 0}"
            )

        # Log timing statistics
        logger.info("⏱️  Timing Statistics (average times per operation):")
        timing_parts = []
        for operation in ['frame_capture', 'quality_analysis', 'frame_rotation', 'frame_resize', 'frame_save',
                          'jpg_encoding', 'post_request', 'frame_write']:
            count = self.timing_counts[operation]
            if count > 0:
                avg_time = (self.timing_stats[operation] / count) * 1000  # Convert to ms
                timing_parts.append(f"{operation.replace('_', ' ').title()}: {avg_time:.2f}ms")

        if timing_parts:
            for part in timing_parts:
                logger.info(f"  • {part}")

    def run(self):
        """
        Start the filtering pipeline.
        """
        self.running = True
        self.start_time = time.time()

        logger.info("=== Stream Quality Filter ===")
        logger.info(f"Input: {self.input_rtsp_url}")
        if self.output_rtsp_url:
            logger.info(f"Output Stream: {self.output_rtsp_url}")
        if self.output_file:
            logger.info(f"Output File: {self.output_file}")
        if self.post_url:
            logger.info(f"POST URL: {self.post_url}")
            logger.info(f"POST Question: {self.post_question}")
        if self.save_latest_frame:
            logger.info(f"Saving latest frame to: {self.save_latest_frame}")
        logger.info("Starting pipeline...")

        # Start capture thread
        capture_thread = threading.Thread(target=self.capture_and_filter_frames, daemon=False)
        capture_thread.start()

        # Start POST thread if enabled
        post_thread = None
        if self.post_url:
            post_thread = threading.Thread(target=self.post_frames, daemon=False)
            post_thread.start()

        # Start writing thread (this blocks)
        try:
            self.write_frames()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Error in writing: {e}", exc_info=True)
        finally:
            self.stop()

        # Wait for threads
        capture_thread.join(timeout=5.0)
        if post_thread:
            post_thread.join(timeout=5.0)

    def stop(self):
        """
        Stop the pipeline and cleanup.
        """
        logger.info("Stopping pipeline...")
        self.running = False

        if self.cap:
            self.cap.release()

        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.stdin.close()
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=5.0)
            except:
                self.ffmpeg_process.kill()

        if self.video_writer:
            self.video_writer.release()

        if self.show_preview:
            cv2.destroyAllWindows()

        self._log_stats()
        logger.info("Pipeline stopped")


def main():
    parser = argparse.ArgumentParser(
        description='Filter RTSP stream by quality (blur/brightness) and output to new stream and/or file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Output to RTSP stream only
  %(prog)s rtsp://192.168.9.21:8554/live/str --output-stream rtsp://localhost:8554/filtered

  # Output to file only
  %(prog)s rtsp://192.168.9.21:8554/live/str --output-file filtered.mp4

  # Output to both stream and file
  %(prog)s rtsp://192.168.9.21:8554/live/str --output-stream rtsp://localhost:8554/filtered --output-file filtered.mp4

  # POST filtered frames to API endpoint
  %(prog)s rtsp://192.168.9.21:8554/live/str --post-url https://192.168.9.244:8080/qa --post-question "What do you see?" --post-no-verify-ssl

  # Output to file AND POST to API
  %(prog)s rtsp://192.168.9.21:8554/live/str --output-file filtered.mp4 --post-url https://192.168.9.244:8080/qa --post-no-verify-ssl

  # Custom quality thresholds
  %(prog)s rtsp://192.168.9.21:8554/live/str --output-file filtered.mp4 --blur 150 --brightness-min 60 --brightness-max 220

  # With preview window
  %(prog)s rtsp://192.168.9.21:8554/live/str --output-file filtered.mp4 --preview

Note: For streaming output, make sure you have MediaMTX running:
  docker run --rm -it -p 8554:8554 bluenviron/mediamtx
        """
    )

    parser.add_argument(
        'input_url',
        help='Input RTSP stream URL'
    )

    parser.add_argument(
        '--output-stream',
        help='Output RTSP stream URL (optional)'
    )

    parser.add_argument(
        '--output-file',
        help='Output video file path (optional, e.g. filtered.mp4)'
    )

    parser.add_argument(
        '--blur',
        type=float,
        default=100.0,
        help='Blur threshold - higher = sharper required (default: 100.0)'
    )

    parser.add_argument(
        '--brightness-min',
        type=float,
        default=50.0,
        help='Minimum brightness threshold 0-255 (default: 50.0)'
    )

    parser.add_argument(
        '--brightness-max',
        type=float,
        default=250.0,
        help='Maximum brightness threshold 0-255 (default: 250.0)'
    )

    parser.add_argument(
        '--buffer',
        type=int,
        default=30,
        help='Frame buffer size (default: 30)'
    )

    parser.add_argument(
        '--preview',
        action='store_true',
        help='Show preview window with quality metrics'
    )

    parser.add_argument(
        '--post-url',
        help='POST filtered frames to this URL (e.g., https://192.168.9.244:8080/qa)'
    )

    parser.add_argument(
        '--post-question',
        default='What do you see in this image?',
        help='Question to send with each frame (default: "What do you see in this image?")'
    )

    parser.add_argument(
        '--post-no-verify-ssl',
        action='store_true',
        help='Disable SSL certificate verification for POST requests'
    )

    parser.add_argument(
        '--post-timeout',
        type=int,
        default=10,
        help='POST request timeout in seconds (default: 10)'
    )

    parser.add_argument(
        '--post-jpg-quality',
        type=int,
        default=95,
        help='JPEG quality for posted frames 0-100 (default: 95)'
    )

    parser.add_argument(
        '--post-rotate-90',
        action='store_true',
        help='Rotate frames 90 degrees clockwise before POSTing (for POST only, does not affect file/stream output)'
    )

    parser.add_argument(
        '--target-width',
        type=int,
        help='Target width for resizing frames before POSTing (must specify both width and height)'
    )

    parser.add_argument(
        '--target-height',
        type=int,
        help='Target height for resizing frames before POSTing (must specify both width and height)'
    )

    parser.add_argument(
        '--min-frame-interval',
        type=float,
        default=0.0,
        help='Minimum time interval (in seconds) between selected frames (default: 0.0, disabled)'
    )

    parser.add_argument(
        '--save-latest-frame',
        help='Path to save the latest processed frame (continuously updated, e.g. latest_frame.jpg)'
    )

    parser.add_argument(
        '--low-latency',
        action='store_true',
        help='Enable low latency mode - aggressively flush buffers to get latest frames (may skip frames)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.output_stream and not args.output_file and not args.post_url:
        parser.error("Must specify at least one output: --output-stream, --output-file, or --post-url")

    # Validate target resolution
    if (args.target_width is not None) != (args.target_height is not None):
        parser.error("Must specify both --target-width and --target-height, or neither")

    target_resolution = None
    if args.target_width and args.target_height:
        target_resolution = (args.target_width, args.target_height)

    # Generate default output filename if needed
    if args.output_file and not args.output_file.endswith(('.mp4', '.avi', '.mkv')):
        args.output_file += '.mp4'

    filter_pipeline = StreamQualityFilter(
        input_rtsp_url=args.input_url,
        output_rtsp_url=args.output_stream,
        output_file=args.output_file,
        blur_threshold=args.blur,
        brightness_min=args.brightness_min,
        brightness_max=args.brightness_max,
        buffer_size=args.buffer,
        show_preview=args.preview,
        post_url=args.post_url,
        post_question=args.post_question,
        post_verify_ssl=not args.post_no_verify_ssl,
        post_timeout=args.post_timeout,
        post_jpg_quality=args.post_jpg_quality,
        min_frame_interval=args.min_frame_interval,
        post_rotate_90=args.post_rotate_90,
        save_latest_frame=args.save_latest_frame,
        low_latency_mode=args.low_latency,
        target_resolution=target_resolution
    )

    try:
        filter_pipeline.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        filter_pipeline.stop()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        filter_pipeline.stop()
        sys.exit(1)


if __name__ == '__main__':
    main()

