"""
Data Harvester API Endpoints

Control the Data Harvester mode via REST API.
"""

import logging
from fastapi import APIRouter, HTTPException

from app.services.data_harvester import data_harvester
from app.services.data_augmentor import data_augmentor

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


# ============================================================================
# Data Augmentation Endpoints
# ============================================================================

@router.post("/augment/run")
async def run_augmentation():
    """
    Run data augmentation on all class folders.
    
    Generates augmented versions of original images:
    - aug_flip_* : Horizontally mirrored
    - aug_dark_* : 30% darker
    - aug_bright_* : 30% brighter
    
    Skips already-augmented images (files starting with aug_).
    """
    try:
        logger.info("Starting data augmentation...")
        result = data_augmentor.augment_all()
        logger.info(f"Augmentation complete: {result.get('total_images_generated', 0)} images generated")
        return {
            "status": "complete",
            "message": f"Generated {result.get('total_images_generated', 0)} augmented images",
            "result": result
        }
    except Exception as e:
        logger.error(f"Failed to run augmentation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/augment/stats")
async def get_augmentation_stats():
    """
    Get statistics about original vs augmented images per class.
    
    Returns count of original and augmented images for each class folder.
    """
    return data_augmentor.get_stats()
