import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify():
    logger.info("Verifying Audio Pipeline Components...")

    try:
        logger.info("1. Importing Dependencies...")
        import vosk
        import openwakeword
        import webrtcvad
        import numpy
        logger.info("Dependencies imported successfully.")
    except ImportError as e:
        logger.error(f"Dependency missing: {e}")
        return

    try:
        logger.info("2. Importing Services...")
        from app.services.audio_stream_reader import AudioStreamReader
        from app.services.audio_analyzer import AudioAnalyzer
        from app.services.agent_service import AgentService
        logger.info("Services imported successfully.")
    except ImportError as e:
        logger.error(f"Service import failed: {e}")
        return

    try:
        logger.info("3. Instantiating AudioAnalyzer...")
        analyzer = AudioAnalyzer()
        # We won't call initialize_models() as it might download things or fail without models
        # But we can check if attributes exist
        assert analyzer.state == "LISTENING"
        logger.info("AudioAnalyzer instantiated.")
    except Exception as e:
        logger.error(f"AudioAnalyzer instantiation failed: {e}")
        return

    try:
        logger.info("4. Instantiating AgentService...")
        # AgentService subscribes to event bus on init
        agent = AgentService()
        logger.info("AgentService instantiated.")
    except Exception as e:
        logger.error(f"AgentService instantiation failed: {e}")
        return

    logger.info("Verification Complete: Code structure seems correct.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(verify())
