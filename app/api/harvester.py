"""
Data Harvester API Endpoints

Control the Data Harvester mode via REST API.
"""

import logging
from fastapi import APIRouter, HTTPException

from app.services.data_harvester import data_harvester

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/harvester/start")
async def start_harvester():
    """
    Start the Data Harvester mode.
    
    Opens a CV2 window displaying the livestream.
    Press number keys to save frames to labeled folders.
    """
    try:
        data_harvester.start()
        return {
            "status": "started",
            "message": "Data Harvester mode started. Press keys 1-9, 0, c to capture frames, 'q' to quit."
        }
    except Exception as e:
        logger.error(f"Failed to start harvester: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/harvester/stop")
async def stop_harvester():
    """
    Stop the Data Harvester mode.
    
    Closes the CV2 window and stops capturing.
    """
    try:
        data_harvester.stop()
        return {"status": "stopped", "message": "Data Harvester mode stopped."}
    except Exception as e:
        logger.error(f"Failed to stop harvester: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/harvester/status")
async def get_harvester_status():
    """
    Get the current status of the Data Harvester.
    
    Returns:
        enabled: Whether harvester mode is active
        base_dir: Directory where labeled frames are saved
        classes: List of available class labels
    """
    return data_harvester.get_status()
