"""
===============================================================================
ASPECT RATIO NORMALIZATION FOR AI MODEL INPUT
===============================================================================

WHY THIS EXISTS:
----------------
Our VLM (PaliGemma) uses a 224x224 square encoder internally. To maximize useful
pixels and avoid wasted bandwidth, we normalize ALL input images to 1:1 SQUARE
aspect ratio.

The Android client already sends 720x720 square frames, so most frames pass
through unchanged (fast path). Non-square frames from other sources get
center-cropped to square to avoid adding black borders that waste encoder pixels.

OPTIMIZATION RATIONALE:
-----------------------
- PaliGemma resizes everything to 224x224 internally
- Square input = 100% of encoder pixels contain useful data
- 16:9 input = ~44% of pixels wasted as letterbox bars
- 720x720 -> 224x224 is a clean 3.2x downscale

HOW IT WORKS:
-------------
1. Check if image is already square (within 2% tolerance) -> fast pass-through
2. Non-square images get CENTER-CROPPED to square (no black borders)
3. Optional: Downscale to target resolution for bandwidth savings

EXAMPLES:
---------
- 720x720 square -> passed through unchanged (fast path)
- 1920x1080 (16:9) -> center-cropped to 1080x1080
- 1080x1920 (9:16) -> center-cropped to 1080x1080
- 640x480 (4:3) -> center-cropped to 480x480

LOGGING:
--------
All normalization operations are logged with the [ASPECT_RATIO] tag for easy
filtering in logs:
    grep -i "ASPECT_RATIO" app.log

===============================================================================
"""

import logging
from typing import Tuple, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Target aspect ratio: 1:1 (Square)
# PaliGemma VLM uses 224x224 square encoder - square input maximizes useful pixels
TARGET_ASPECT_RATIO = 1.0  # width / height = 1.0 (square)

# Tolerance for aspect ratio comparison (to avoid unnecessary processing)
ASPECT_RATIO_TOLERANCE = 0.02  # 2% tolerance


def normalize_to_square_aspect_ratio(
    frame_bytes: bytes,
    target_ratio: float = TARGET_ASPECT_RATIO
) -> bytes:
    """
    Normalize an image to 1:1 square aspect ratio by CENTER-CROPPING.

    ==========================================================================
    WHY: PaliGemma VLM uses a 224x224 square encoder. Center-cropping to square
    maximizes useful pixels (no black borders wasting encoder capacity).
    ==========================================================================

    Args:
        frame_bytes: JPEG-encoded image bytes
        target_ratio: Target width/height ratio (default: 1.0 for square)

    Returns:
        JPEG-encoded image bytes with 1:1 square aspect ratio
    """
    try:
        # =================================================================
        # FAST PATH: Check dimensions from JPEG header without full decode
        # This avoids ~20ms decode overhead for images already square
        # Android client sends 720x720 so this should be the common case
        # =================================================================
        fast_width, fast_height = _get_jpeg_dimensions_fast(frame_bytes)
        if fast_width and fast_height:
            fast_ratio = fast_width / fast_height
            if abs(fast_ratio - target_ratio) <= ASPECT_RATIO_TOLERANCE:
                logger.debug(
                    f"[ASPECT_RATIO] FAST SKIP: Image already square "
                    f"({fast_width}x{fast_height}, ratio={fast_ratio:.3f})"
                )
                return frame_bytes

        # Full decode needed for non-square images
        nparr = np.frombuffer(frame_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            logger.error("[ASPECT_RATIO] Failed to decode image bytes")
            return frame_bytes

        original_height, original_width = img.shape[:2]
        original_ratio = original_width / original_height

        # Double-check ratio (in case fast check failed)
        if abs(original_ratio - target_ratio) <= ASPECT_RATIO_TOLERANCE:
            logger.debug(
                f"[ASPECT_RATIO] Image already at target ratio "
                f"({original_width}x{original_height}, ratio={original_ratio:.3f})"
            )
            return frame_bytes

        # CENTER-CROP to square (use the smaller dimension)
        crop_size = min(original_width, original_height)
        crop_x = (original_width - crop_size) // 2
        crop_y = (original_height - crop_size) // 2

        cropped = img[crop_y:crop_y + crop_size, crop_x:crop_x + crop_size]

        # Encode back to JPEG
        _, buffer = cv2.imencode('.jpg', cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
        normalized_bytes = buffer.tobytes()

        # Log the normalization with clear tagging for easy grep
        logger.info(
            f"[ASPECT_RATIO] Center-cropped to square: "
            f"{original_width}x{original_height} (ratio={original_ratio:.3f}) -> "
            f"{crop_size}x{crop_size} (square) | "
            f"Crop offset: x={crop_x}px, y={crop_y}px | "
            f"Reason: PaliGemma 224x224 square encoder"
        )

        return normalized_bytes

    except Exception as e:
        logger.error(f"[ASPECT_RATIO] Normalization failed: {e}", exc_info=True)
        # Return original on error to avoid breaking the pipeline
        return frame_bytes


# Backwards compatibility alias
normalize_to_landscape_aspect_ratio = normalize_to_square_aspect_ratio


def _get_jpeg_dimensions_fast(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract image dimensions from JPEG header without full decode.
    
    This parses the JPEG markers to find SOF (Start of Frame) which contains
    the image dimensions. Much faster than full cv2.imdecode (~0.1ms vs ~20ms).
    
    Returns:
        Tuple of (width, height) or (None, None) if parsing fails
    """
    try:
        # JPEG must start with SOI marker (0xFFD8)
        if len(data) < 2 or data[0] != 0xFF or data[1] != 0xD8:
            return None, None
        
        pos = 2
        while pos < len(data) - 1:
            # Find next marker
            if data[pos] != 0xFF:
                pos += 1
                continue
            
            marker = data[pos + 1]
            
            # Skip padding bytes
            if marker == 0xFF:
                pos += 1
                continue
            
            # SOF markers (Start of Frame) contain dimensions
            # SOF0 (0xC0) = Baseline DCT
            # SOF2 (0xC2) = Progressive DCT
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                # SOF structure: marker(2) + length(2) + precision(1) + height(2) + width(2)
                if pos + 9 <= len(data):
                    height = (data[pos + 5] << 8) | data[pos + 6]
                    width = (data[pos + 7] << 8) | data[pos + 8]
                    return width, height
                return None, None
            
            # Skip other markers
            if marker == 0xD9:  # EOI (End of Image)
                return None, None
            if marker == 0x00 or (0xD0 <= marker <= 0xD7):  # Standalone markers
                pos += 2
                continue
            
            # Variable-length marker - read length and skip
            if pos + 4 <= len(data):
                length = (data[pos + 2] << 8) | data[pos + 3]
                pos += 2 + length
            else:
                return None, None
        
        return None, None
        
    except Exception:
        return None, None


def _calculate_center_crop(
    width: int,
    height: int
) -> Tuple[int, int, int, int]:
    """
    Calculate center-crop dimensions to achieve square aspect ratio.

    For square target:
    - Landscape images: crop left/right edges
    - Portrait images: crop top/bottom edges

    Returns:
        Tuple of (crop_size, crop_size, crop_x, crop_y)
    """
    crop_size = min(width, height)
    crop_x = (width - crop_size) // 2
    crop_y = (height - crop_size) // 2

    return crop_size, crop_size, crop_x, crop_y


def get_aspect_ratio_info(frame_bytes: bytes) -> dict:
    """
    Get information about an image's aspect ratio and what normalization would occur.
    Useful for debugging and monitoring.

    Returns:
        Dict with original dimensions, ratio, and normalization details
    """
    try:
        nparr = np.frombuffer(frame_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return {"error": "Failed to decode image"}

        height, width = img.shape[:2]
        ratio = width / height
        needs_normalization = abs(ratio - TARGET_ASPECT_RATIO) > ASPECT_RATIO_TOLERANCE

        info = {
            "original_width": width,
            "original_height": height,
            "original_ratio": round(ratio, 4),
            "target_ratio": TARGET_ASPECT_RATIO,
            "target_description": "1:1 Square (PaliGemma 224x224)",
            "needs_normalization": needs_normalization,
            "format_description": _describe_format(ratio)
        }

        if needs_normalization:
            crop_w, crop_h, crop_x, crop_y = _calculate_center_crop(width, height)
            info["normalized_width"] = crop_w
            info["normalized_height"] = crop_h
            info["crop_x"] = crop_x
            info["crop_y"] = crop_y
            info["normalization_type"] = "center-crop"

        return info

    except Exception as e:
        return {"error": str(e)}


def _describe_format(ratio: float) -> str:
    """Describe common aspect ratios for logging clarity."""
    if abs(ratio - 1.0) < 0.05:
        return "1:1 Square (TARGET - optimal for PaliGemma)"
    elif abs(ratio - 16/9) < 0.05:
        return "16:9 Landscape"
    elif abs(ratio - 9/16) < 0.05:
        return "9:16 Portrait"
    elif abs(ratio - 4/3) < 0.05:
        return "4:3 Standard"
    elif abs(ratio - 3/4) < 0.05:
        return "3:4 Portrait"
    elif ratio > 1:
        return f"Landscape ({ratio:.2f}:1)"
    else:
        return f"Portrait (1:{1/ratio:.2f})"
