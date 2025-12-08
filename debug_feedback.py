import asyncio
import httpx
import logging
import sys
import os

# Add current directory to path to allow imports
sys.path.append(os.getcwd())

from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_feedback(camera_id: str):
    base_url = settings.MENTRA_URL
    logger.info(f"Testing feedback for Camera ID: {camera_id}")
    logger.info(f"Target URL: {base_url}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test 1: Step Notification
        logger.info("\n--- Testing /on_step ---")
        try:
            url = f"{base_url}/on_step"
            payload = {"username": camera_id, "text": "Debug step notification"}
            logger.info(f"Sending POST to {url} with payload: {payload}")
            response = await client.post(url, json=payload)
            logger.info(f"Response: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Failed to send step notification: {e}")

        # Test 2: Agent Reply
        logger.info("\n--- Testing /agent_reply ---")
        try:
            url = f"{base_url}/agent_reply"
            payload = {"username": camera_id, "text": "This is a debug reply from the script."}
            logger.info(f"Sending POST to {url} with payload: {payload}")
            response = await client.post(url, json=payload)
            logger.info(f"Response: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Failed to send agent reply: {e}")

        # Test 3: Progress Notification
        logger.info("\n--- Testing /progress_step ---")
        try:
            url = f"{base_url}/progress_step"
            payload = {
                "username": camera_id,
                "text": "progress",
                "from_step": 1,
                "to_step": 2
            }
            logger.info(f"Sending POST to {url} with payload: {payload}")
            response = await client.post(url, json=payload)
            logger.info(f"Response: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Failed to send progress notification: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cam_id = sys.argv[1]
    else:
        cam_id = input("Enter Camera ID (username) to test [default: test_camera]: ").strip() or "test_camera"
    
    asyncio.run(test_feedback(cam_id))
