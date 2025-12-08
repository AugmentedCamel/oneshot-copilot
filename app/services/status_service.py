"""Service for managing user procedure status JSON files."""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional
from threading import Lock

logger = logging.getLogger(__name__)

# Thread-safe file writing
_write_lock = Lock()

# Base directory for user status files
# Use absolute path relative to this file to ensure it works regardless of CWD
STATUS_DIR = Path(__file__).parent.parent / "data" / "user_status"


def ensure_status_directory() -> None:
    """Create the status directory if it doesn't exist."""
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Status directory ensured: {STATUS_DIR}")


def get_status_file_path(username: str, procedure_id: str) -> Path:
    """
    Get the file path for a user's status file.
    
    Args:
        username: Username
        procedure_id: Procedure ID
        
    Returns:
        Path to the status file
    """
    # Sanitize filename components to avoid path traversal
    safe_username = "".join(c for c in username if c.isalnum() or c in ('-', '_'))
    safe_proc_id = "".join(c for c in procedure_id if c.isalnum() or c in ('-', '_', '@'))
    filename = f"{safe_username}_{safe_proc_id}.json"
    return STATUS_DIR / filename


def save_user_status(username: str, status_data: Dict) -> None:
    """
    Save user status to JSON file.
    Thread-safe operation.
    
    Args:
        username: Username
        status_data: Status dictionary containing username, id, name, version, and steps
    """
    if not status_data:
        logger.warning(f"Attempted to save null status data for user: {username}")
        return
    
    procedure_id = status_data.get("id")
    if not procedure_id:
        logger.warning(f"Status data missing procedure id for user: {username}")
        return
    
    try:
        # Ensure directory exists
        ensure_status_directory()
        
        # Get file path
        file_path = get_status_file_path(username, procedure_id)
        
        # Thread-safe write
        with _write_lock:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(status_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"User status saved - username={username}, procedure={procedure_id}, file={file_path}")
    except Exception as e:
        logger.error(f"Failed to save user status - username={username}, error: {str(e)}", exc_info=True)


def load_user_status(username: str, procedure_id: str) -> Optional[Dict]:
    """
    Load user status from JSON file.
    
    Args:
        username: Username
        procedure_id: Procedure ID
        
    Returns:
        Status dictionary or None if file doesn't exist
    """
    try:
        file_path = get_status_file_path(username, procedure_id)
        
        if not file_path.exists():
            logger.debug(f"Status file not found - username={username}, procedure={procedure_id}")
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            status_data = json.load(f)
        
        logger.debug(f"User status loaded - username={username}, procedure={procedure_id}")
        return status_data
    except Exception as e:
        logger.error(f"Failed to load user status - username={username}, error: {str(e)}", exc_info=True)
        return None


def delete_user_status(username: str, procedure_id: str) -> bool:
    """
    Delete user status file.
    
    Args:
        username: Username
        procedure_id: Procedure ID
        
    Returns:
        True if file was deleted, False otherwise
    """
    try:
        file_path = get_status_file_path(username, procedure_id)
        
        if file_path.exists():
            file_path.unlink()
            logger.info(f"User status file deleted - username={username}, procedure={procedure_id}")
            return True
        else:
            logger.debug(f"Status file not found for deletion - username={username}, procedure={procedure_id}")
            return False
    except Exception as e:
        logger.error(f"Failed to delete user status - username={username}, error: {str(e)}", exc_info=True)
        return False


def delete_all_user_status(username: str) -> int:
    """
    Delete all status files for a given username.
    This is useful when starting a new procedure to clean up any previous procedure files.
    
    Args:
        username: Username
        
    Returns:
        Number of files deleted
    """
    try:
        ensure_status_directory()
        
        # Sanitize username to match filename pattern
        safe_username = "".join(c for c in username if c.isalnum() or c in ('-', '_'))
        
        # Find all files matching the username pattern
        pattern = f"{safe_username}_*.json"
        matching_files = list(STATUS_DIR.glob(pattern))
        
        deleted_count = 0
        for file_path in matching_files:
            try:
                file_path.unlink()
                logger.info(f"Deleted user status file - username={username}, file={file_path.name}")
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete file {file_path.name}: {str(e)}")
        
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} status file(s) for username={username}")
        else:
            logger.debug(f"No status files found to delete for username={username}")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to delete user status files - username={username}, error: {str(e)}", exc_info=True)
        return 0


def get_active_status(username: str) -> Optional[Dict]:
    """
    Get the active status for a user.
    Finds the most recently modified status file for the user.
    
    Args:
        username: Username (or camera_id)
        
    Returns:
        Status dictionary or None if no active status found
    """
    try:
        ensure_status_directory()
        
        # Sanitize username
        safe_username = "".join(c for c in username if c.isalnum() or c in ('-', '_'))
        
        # Find all files matching the username pattern
        pattern = f"{safe_username}_*.json"
        matching_files = list(STATUS_DIR.glob(pattern))
        
        if not matching_files:
            return None
            
        # Sort by modification time, newest first
        matching_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        # Load the newest file
        latest_file = matching_files[0]
        
        with open(latest_file, 'r', encoding='utf-8') as f:
            status_data = json.load(f)
            
        return status_data
        
    except Exception as e:
        logger.error(f"Failed to get active status - username={username}, error: {str(e)}", exc_info=True)
        return None