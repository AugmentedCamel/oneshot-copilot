"""
Data Harvester Service

Captures frames from the livestream and saves them to labeled folders based on keypress input.
Used for building training datasets for LoRA when no procedure is running.

TODO: The display loop currently blocks. Consider running in a separate thread if this
becomes problematic for the main application.
"""

import cv2
import os
import logging
import threading
from datetime import datetime
from typing import Optional

from app.core.event_bus import event_bus, EventType, Event
from app.core.frame_store import get_frame
from app.services.harvester_config import KEY_MAP, DEFAULT_BASE_DIR

logger = logging.getLogger(__name__)


class DataHarvesterService:
    """
    Service for capturing and labeling frames from the livestream.
    
    When enabled, displays the stream in a CV2 window and allows
    users to press keys to save frames to labeled folders.
    """
    
    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or DEFAULT_BASE_DIR
        self.enabled = False
        self._latest_frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._display_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
    def _ensure_dirs(self):
        """Create output directories for all classes."""
        logger.info(f"Creating Data Lake at {self.base_dir}")
        for key, folder in KEY_MAP.items():
            path = os.path.join(self.base_dir, folder)
            os.makedirs(path, exist_ok=True)
            logger.debug(f" [OK] /{folder}")
    
    def start(self):
        """Start the data harvester mode."""
        if self.enabled:
            logger.warning("Data Harvester is already running")
            return
        
        logger.info("Starting Data Harvester mode...")
        self._ensure_dirs()
        
        self.enabled = True
        self._stop_event.clear()
        
        # Subscribe to frame events
        event_bus.subscribe(EventType.FRAME_CREATED, self._on_frame_created)
        
        # Start display thread
        # TODO: Currently blocking in its own thread. Consider architecture implications.
        self._display_thread = threading.Thread(target=self._display_loop, daemon=True)
        self._display_thread.start()
        
        logger.info("Data Harvester mode started - Press keys 1-9, 0, c to capture frames, 'q' to quit")
    
    def stop(self):
        """Stop the data harvester mode."""
        if not self.enabled:
            logger.warning("Data Harvester is not running")
            return
        
        logger.info("Stopping Data Harvester mode...")
        self.enabled = False
        self._stop_event.set()
        
        # Unsubscribe from events
        event_bus.unsubscribe(EventType.FRAME_CREATED, self._on_frame_created)
        
        # Wait for display thread to finish
        if self._display_thread:
            self._display_thread.join(timeout=2.0)
            self._display_thread = None
        
        # Close any open CV2 windows
        cv2.destroyAllWindows()
        
        logger.info("Data Harvester mode stopped")
    
    async def _on_frame_created(self, event: Event):
        """Handle new frame from the stream."""
        frame = event.payload.get("frame")
        if not frame:
            return
        
        # Get frame bytes from store
        frame_bytes = get_frame(frame.id)
        if frame_bytes:
            with self._frame_lock:
                self._latest_frame = frame_bytes
    
    def _draw_key_guide(self, frame):
        """Draw a key mapping guide overlay on the frame."""
        # Define key mapping organized by category
        key_mapping = [
            ("KEYBOARD GUIDE", None, (255, 255, 255)),  # Header
            ("", None, None),  # Spacer
            ("Door States:", None, (100, 200, 255)),
            ("1", "open_door_dishwasher", (255, 255, 255)),
            ("9", "closed_door_dishwasher", (255, 255, 255)),
            ("", None, None),
            ("Rack States:", None, (100, 200, 255)),
            ("2", "removed_rack_bottom", (255, 255, 255)),
            ("8", "inserted_rack_bottom", (255, 255, 255)),
            ("", None, None),
            ("Reservoir Cap:", None, (100, 200, 255)),
            ("3", "detached_cap_reservoir", (255, 255, 255)),
            ("7", "attached_cap_reservoir", (255, 255, 255)),
            ("", None, None),
            ("Funnel States:", None, (100, 200, 255)),
            ("4", "inserted_funnel_reservoir", (255, 255, 255)),
            ("6", "removed_funnel_reservoir", (255, 255, 255)),
            ("", None, None),
            ("Actions:", None, (100, 200, 255)),
            ("5", "pouring_salt_granular", (255, 255, 255)),
            ("", None, None),
            ("Errors & Recovery:", None, (100, 200, 255)),
            ("0", "spill_salt_floor", (255, 255, 255)),
            ("c", "clean_floor_stainless", (255, 255, 255)),
            ("", None, None),
            ("Null Class:", None, (100, 200, 255)),
            ("i", "class_irrelevant", (255, 255, 255)),
            ("", None, None),
            ("Controls:", None, (255, 100, 100)),
            ("q", "Quit Harvester", (255, 100, 100)),
        ]
        
        # Panel configuration
        panel_x = frame.shape[1] - 450
        panel_y = 10
        panel_width = 440
        line_height = 24
        panel_height = len(key_mapping) * line_height + 20
        
        # Draw semi-transparent background panel
        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, panel_y), 
                     (panel_x + panel_width, panel_y + panel_height),
                     (40, 40, 40), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
        
        # Draw border
        cv2.rectangle(frame, (panel_x, panel_y),
                     (panel_x + panel_width, panel_y + panel_height),
                     (100, 100, 100), 2)
        
        # Draw text
        y_offset = panel_y + 30
        for key, label, color in key_mapping:
            if label is None and key == "":
                # Spacer line
                y_offset += line_height // 2
                continue
            
            if label is None:
                # Category header
                cv2.putText(frame, key, (panel_x + 15, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            else:
                # Key mapping entry
                key_text = f"[{key}]"
                cv2.putText(frame, key_text, (panel_x + 15, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                cv2.putText(frame, label, (panel_x + 65, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
            
            y_offset += line_height

    
    def _display_loop(self):
        """
        Main display loop with keyboard capture.
        
        TODO: This loop blocks in its own thread. If we need better integration
        with the main event loop, consider using asyncio-compatible approaches.
        """
        flash_timer = 0
        last_saved_info = ""
        
        logger.info("Data Harvester display loop started")
        
        while self.enabled and not self._stop_event.is_set():
            # Get the latest frame
            with self._frame_lock:
                frame_bytes = self._latest_frame
            
            if frame_bytes is None:
                # No frame yet, wait a bit
                cv2.waitKey(100)
                continue
            
            # Decode frame
            import numpy as np
            frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            
            if frame is None:
                cv2.waitKey(100)
                continue
            
            # Key Listener (1ms wait for responsiveness)
            key = cv2.waitKey(1) & 0xFF
            
            if key in KEY_MAP:
                label = KEY_MAP[key]
                self._save_frame(frame, label)
                last_saved_info = f"{label} (Saved)"
                flash_timer = 5
                logger.info(f"CAPTURED: [{label}]")
            
            elif key == ord('q'):
                logger.info("Quit key pressed, stopping harvester...")
                self.enabled = False
                break
            
            # Draw key mapping guide
            self._draw_key_guide(frame)
            
            # UI Overlay - Last saved info
            cv2.putText(frame, f"Last: {last_saved_info}", (50, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            # Visual Feedback (Screen Flash)
            if flash_timer > 0:
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (255, 255, 255), -1)
                cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame)
                cv2.putText(frame, "SAVED", (100, 300), 
                            cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 255), 4)
                flash_timer -= 1
            
            # Resize for display if needed
            display_frame = cv2.resize(frame, (1280, 720))
            cv2.imshow('OneShot Data Harvester', display_frame)
        
        cv2.destroyAllWindows()
        logger.info("Data Harvester display loop ended")
    
    def _save_frame(self, frame, label: str):
        """Save a frame to the labeled folder."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{label}_{timestamp}.jpg"
        save_path = os.path.join(self.base_dir, label, filename)
        
        cv2.imwrite(save_path, frame)
        logger.debug(f"Saved: {save_path}")
    
    def get_status(self) -> dict:
        """Get the current status of the harvester."""
        return {
            "enabled": self.enabled,
            "base_dir": self.base_dir,
            "classes": list(KEY_MAP.values())
        }


# Singleton instance
data_harvester = DataHarvesterService()
