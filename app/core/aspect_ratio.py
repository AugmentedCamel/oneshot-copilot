"""
===============================================================================
ASPECT RATIO NORMALIZATION FOR AI MODEL INPUT
===============================================================================

WHY THIS EXISTS:
----------------
Our AI model was trained on images in 16:9 LANDSCAPE aspect ratio (width:height).
Input images from different sources (cameras, streams, uploads) may arrive in
various aspect ratios (9:16 portrait, 4:3, 1:1 square, etc.).

To ensure consistent model performance, we normalize ALL input images to 16:9
by adding BLACK BORDERS (pillarboxing) rather than cropping or stretching,
which would lose information or introduce distortion.

HOW IT WORKS:
-------------
1. Calculate the target 16:9 dimensions based on input image size
2. Create a black canvas with the target dimensions
3. Center the original image on the canvas
4. Return the normalized image bytes

EXAMPLES:
---------
- 9:16 portrait (1080x1920) -> adds black bars left/right (pillarbox)
- 4:3 image (640x480) -> adds black bars left/right to reach 16:9
- Square (500x500) -> adds black bars left/right to reach 16:9
- Already 16:9 -> passed through unchanged

LOGGING:
--------
All normalization operations are logged with the [ASPECT_RATIO] tag for easy
filtering in logs:
    grep -i "ASPECT_RATIO" app.log

===============================================================================
"""

import io
import logging
from typing import Tuple, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Target aspect ratio: 16:9 (Landscape/Horizontal)
# This is the format our AI model was trained on
TARGET_ASPECT_RATIO = 16 / 9  # width / height = 1.778

# Tolerance for aspect ratio comparison (to avoid unnecessary processing)
ASPECT_RATIO_TOLERANCE = 0.02  # 2% tolerance


def normalize_to_landscape_aspect_ratio(
    frame_bytes: bytes,
    target_ratio: float = TARGET_ASPECT_RATIO
) -> bytes:
    """
    Normalize an image to 16:9 landscape aspect ratio by adding black borders.
    
    ==========================================================================
    WHY: Our AI model was trained on 16:9 landscape images. This function
    ensures all input images match that format without cropping or stretching.
    ==========================================================================
    
    Args:
        frame_bytes: JPEG-encoded image bytes
        target_ratio: Target width/height ratio (default: 16/9 = 1.778)
    
    Returns:
        JPEG-encoded image bytes with 16:9 aspect ratio
    """
    try:
        # =================================================================
        # FAST PATH: Check dimensions from JPEG header without full decode
        # This avoids ~20ms decode overhead for images already at 16:9
        # =================================================================
        fast_width, fast_height = _get_jpeg_dimensions_fast(frame_bytes)
        if fast_width and fast_height:
            fast_ratio = fast_width / fast_height
            if abs(fast_ratio - target_ratio) <= ASPECT_RATIO_TOLERANCE:
                logger.debug(
                    f"[ASPECT_RATIO] FAST SKIP: Image already 16:9 "
                    f"({fast_width}x{fast_height}, ratio={fast_ratio:.3f})"
                )
                return frame_bytes
        
        # Full decode needed for non-16:9 images
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
        
        # Calculate new dimensions to achieve target ratio
        new_width, new_height, pad_top, pad_left = _calculate_canvas_dimensions(
            original_width, original_height, target_ratio
        )
        
        # Create black canvas and center the original image
        canvas = np.zeros((new_height, new_width, 3), dtype=np.uint8)
        canvas[pad_top:pad_top + original_height, pad_left:pad_left + original_width] = img
        
        # Encode back to JPEG
        _, buffer = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
        normalized_bytes = buffer.tobytes()
        
        # Log the normalization with clear tagging for easy grep
        logger.info(
            f"[ASPECT_RATIO] Normalized image: "
            f"{original_width}x{original_height} (ratio={original_ratio:.3f}) -> "
            f"{new_width}x{new_height} (ratio={target_ratio:.3f}) | "
            f"Padding: top={pad_top}px, left={pad_left}px | "
            f"Reason: AI model trained on 16:9 landscape format"
        )
        
        return normalized_bytes
        
    except Exception as e:
        logger.error(f"[ASPECT_RATIO] Normalization failed: {e}", exc_info=True)
        # Return original on error to avoid breaking the pipeline
        return frame_bytes


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


def _calculate_canvas_dimensions(
    width: int, 
    height: int, 
    target_ratio: float
) -> Tuple[int, int, int, int]:
    """
    Calculate canvas dimensions and padding to achieve target aspect ratio.
    
    For 16:9 landscape target:
    - Landscape images wider than 16:9 get black bars top/bottom (letterbox)
    - Portrait/square images get black bars left/right (pillarbox)
    
    Returns:
        Tuple of (new_width, new_height, pad_top, pad_left)
    """
    current_ratio = width / height
    
    if current_ratio > target_ratio:
        # Image is wider than target -> add padding top/bottom (letterbox)
        # Keep width, calculate new height
        new_width = width
        new_height = int(width / target_ratio)
        pad_top = (new_height - height) // 2
        pad_left = 0
    else:
        # Image is taller than target -> add padding left/right (pillarbox)
        # Keep height, calculate new width
        new_height = height
        new_width = int(height * target_ratio)
        pad_top = 0
        pad_left = (new_width - width) // 2
    
    return new_width, new_height, pad_top, pad_left


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
            "needs_normalization": needs_normalization,
            "format_description": _describe_format(ratio)
        }
        
        if needs_normalization:
            new_w, new_h, pad_t, pad_l = _calculate_canvas_dimensions(width, height, TARGET_ASPECT_RATIO)
            info["normalized_width"] = new_w
            info["normalized_height"] = new_h
            info["padding_top"] = pad_t
            info["padding_left"] = pad_l
            info["padding_type"] = "letterbox" if ratio > TARGET_ASPECT_RATIO else "pillarbox"
        
        return info
        
    except Exception as e:
        return {"error": str(e)}


def _describe_format(ratio: float) -> str:
    """Describe common aspect ratios for logging clarity."""
    if abs(ratio - 16/9) < 0.05:
        return "16:9 Landscape (TARGET)"
    elif abs(ratio - 9/16) < 0.05:
        return "9:16 Portrait"
    elif abs(ratio - 4/3) < 0.05:
        return "4:3 Standard"
    elif abs(ratio - 3/4) < 0.05:
        return "3:4 Portrait"
    elif abs(ratio - 1.0) < 0.05:
        return "1:1 Square"
    elif ratio > 1:
        return f"Landscape ({ratio:.2f}:1)"
    else:
        return f"Portrait (1:{1/ratio:.2f})"
