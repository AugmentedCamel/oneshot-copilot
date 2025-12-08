import cv2
import numpy as np
import time
import logging
from typing import Tuple, Dict

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
        """
        # Convert to grayscale
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        return np.mean(gray)

    @staticmethod
    def is_frame_good(
            frame: np.ndarray,
            blur_threshold: float = 10.0,
            brightness_min: float = 10.0,
            brightness_max: float = 255.0
    ) -> Tuple[bool, str]:
        """
        Analyze frame quality and determine if it should be kept.
        Returns (is_good, reason).
        """
        blur_score = FrameQualityAnalyzer.calculate_blur_score(frame)
        brightness = FrameQualityAnalyzer.calculate_brightness(frame)

        if blur_score < blur_threshold:
            return False, f"Too blurry (score: {blur_score:.1f} < {blur_threshold})"
        
        if brightness < brightness_min:
            return False, f"Too dark (brightness: {brightness:.1f} < {brightness_min})"
            
        if brightness > brightness_max:
            return False, f"Too bright (brightness: {brightness:.1f} > {brightness_max})"

        return True, "OK"


class RateLimiter:
    """
    Simple token bucket rate limiter to control FPS.
    """
    def __init__(self, fps: float):
        self.target_interval = 1.0 / fps
        self.last_process_time = 0.0

    def should_process(self) -> bool:
        """
        Check if enough time has passed since the last processed frame.
        """
        now = time.time()
        if now - self.last_process_time >= self.target_interval:
            self.last_process_time = now
            return True
        return False
