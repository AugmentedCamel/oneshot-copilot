"""
Data Harvester Configuration

Hardcoded class mappings for LoRA training dataset creation.
TODO: Refactor to be dynamically configurable per procedure/project.
"""

# Key mappings for labeling frames
# Maps keyboard key codes to class labels (folder names)
KEY_MAP = {
    # Door States
    ord('1'): "open_door_dishwasher",        # Step 01 & Fallback Assist
    ord('9'): "closed_door_dishwasher",      # Step 09
    
    # Rack States
    ord('2'): "removed_rack_bottom",         # Step 02
    ord('8'): "inserted_rack_bottom",        # Step 08
    
    # Reservoir Cap
    ord('3'): "detached_cap_reservoir",      # Step 03
    ord('7'): "attached_cap_reservoir",      # Step 07
    
    # Funnel States
    ord('4'): "inserted_funnel_reservoir",   # Step 04
    ord('6'): "removed_funnel_reservoir",    # Step 06
    
    # Actions (Dynamic)
    ord('5'): "pouring_salt_granular",       # Step 05 (Action)
    
    # Errors
    ord('0'): "spill_salt_floor",            # Step 05 (Error Trigger)
    
    # Recovery
    ord('c'): "clean_floor_stainless",       # Fallback Wipe
    
    # Mandatory
    ord('i'): "class_irrelevant"             # The "Null" Class
}

# Default base directory for saving labeled frames
DEFAULT_BASE_DIR = "data_lake/proc_change_coffeefilter"
