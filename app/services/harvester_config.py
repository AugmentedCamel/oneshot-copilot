"""
Data Harvester Configuration

Hardcoded class mappings for LoRA training dataset creation.
TODO: Refactor to be dynamically configurable per procedure/project.
"""

# Key mappings for labeling frames
# Maps keyboard key codes to class labels (folder names)
KEY_MAP = {
    # Phase 1: Setup
    ord('1'): "door_fully_open",
    ord('2'): "rack_removed",
    
    # Phase 2: The Core Action
    ord('3'): "lid_removed",
    ord('4'): "funnel_inserted",
    ord('5'): "pouring_salt_action",
    ord('6'): "funnel_removed",
    ord('7'): "lid_closed",
    
    # Phase 3: Finish
    ord('8'): "rack_inserted",
    ord('9'): "door_closed",
    
    # Errors & Recovery
    ord('0'): "error_spill_salt",
    ord('c'): "spill_cleared"
}

# Default base directory for saving labeled frames
DEFAULT_BASE_DIR = "data_lake/proc_refill_dishwasher/auto_labeled"
