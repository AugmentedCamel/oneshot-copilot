"""
Debug logger that writes to a file for easy analysis.
"""
import os
import time
from datetime import datetime
from pathlib import Path

DEBUG_LOG_FILE = Path("debug_trace.log")


def clear_debug_log():
    """Clear the debug log file."""
    if DEBUG_LOG_FILE.exists():
        DEBUG_LOG_FILE.unlink()


def debug_log(component: str, message: str, data: dict = None):
    """
    Write a debug message to the trace file.

    Args:
        component: Name of the component (e.g., "STARTUP", "NODEGRAPH", "EVENT_BUS")
        message: Description of what's happening
        data: Optional dict with relevant data
    """
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    line = f"[{timestamp}] [{component}] {message}"
    if data:
        data_str = " | ".join(f"{k}={v}" for k, v in data.items())
        line += f" | {data_str}"
    line += "\n"

    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def debug_separator(title: str = None):
    """Write a separator line to the debug log."""
    sep = "=" * 80 + "\n"
    if title:
        sep = f"\n{'=' * 30} {title} {'=' * 30}\n"
    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(sep)
