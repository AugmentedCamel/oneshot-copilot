Here is a detailed design plan to integrate the lightweight, always-on "Orlo" voice assistant.

Architectural Design
We will introduce a parallel pipeline dedicated to audio processing. This involves creating an AudioStreamReader to efficiently extract audio using FFmpeg, an AudioAnalyzer to handle the voice pipeline (VAD, Wake Word, STT), and an AgentService that subscribes to events and interacts with the Memory Service.

Code snippet

graph TD
    subgraph Stream Input
        RTMP[RTMP/RTSP Stream]
        V_READER[Video StreamReader (RtspStreamReader)]
        A_READER[AudioStreamReader (FFmpeg)]
    end

    subgraph Audio Pipeline
        ANALYZER[AudioAnalyzer: VAD -> WakeWord 'Orlo' -> STT]
    end

    subgraph Core Services
        EVENT_BUS[Event Bus]
        AGENT_S[AgentService]
        PROC_S[ProcedureService]
        INGEST_S[IngestService]
    end

    RTMP -- Video --> V_READER
    RTMP -- Audio --> A_READER

    V_READER --> INGEST_S
    INGEST_S -- FRAME_CREATED --> EVENT_BUS

    A_READER -- Raw PCM Audio Chunks --> ANALYZER
    ANALYZER -- Transcribed Question --> EVENT_BUS(Publish: QUESTION_ASKED)
    
    EVENT_BUS -- Subscribe: QUESTION_ASKED --> AGENT_S
    
    AGENT_S -- Resolve User/Session ID --> PROC_S
    AGENT_S -- POST /agent/assist --> MEM_S[Memory Service]
1. Technology Stack (Lightweight & Local)
To meet the low CPU usage requirement:

Audio Extraction: FFmpeg (Efficient, already present in the Dockerfile).

VAD & Endpointing: webrtcvad (Highly efficient and lightweight).

Wake Word ("orlo"): OpenWakeWord (Open-source, efficient) or Porcupine (Highly accurate, free tier available).

STT (Transcription): Vosk (Optimized for offline CPU usage, small models available) or Faster-Whisper (using the tiny model).

2. New Component: AudioStreamReader
The existing RtspStreamReader uses OpenCV, which is not ideal for audio. We need a dedicated audio reader.

Location: app/services/audio_stream_reader.py (New file)

Mechanism: Runs in a background thread (similar to RtspStreamReader). Manages an FFmpeg subprocess to decode the stream.

FFmpeg Command: ffmpeg -i [RTMP_URL] -f s16le -acodec pcm_s16le -ar 16000 -ac 1 -vn - (Outputs 16kHz, mono, 16-bit PCM).

Responsibilities: Reads raw audio chunks and uses asyncio.run_coroutine_threadsafe to safely pass them to the AudioAnalyzer on the main event loop. Includes robust reconnection logic.

3. New Component: AudioAnalyzer
This component manages the voice processing logic and state.

Location: app/services/audio_analyzer.py (New file)

Responsibilities:

Initializes the VAD, Wake Word, and STT models.

Processes incoming audio chunks.

Pipeline Flow:

Listen: Continuously feed audio to the Wake Word engine.

Wake: Upon detecting "orlo", switch to TRANSCRIBING state.

Transcribe & Endpoint: Feed audio to the STT engine and VAD. Use VAD to detect silence (e.g., 1.5 seconds) to determine the end of the question.

Finalize: Get the final transcription.

Concurrency Management: The STT process is CPU-intensive. To prevent blocking the FastAPI event loop, the inference must be run in a separate thread pool using asyncio.to_thread or loop.run_in_executor.

Event Emission: Publish the QUESTION_ASKED event to the EventBus.

4. New Service: AgentService
We will decouple the agent interaction logic from the API layer (app/api/agent.py) into a dedicated service that responds to events.

Location: app/services/agent_service.py (New file)

Responsibilities:

Subscribe to the QUESTION_ASKED event.

Handle Event:

Resolve User: Map the source_id (from the event) to a username by querying the ProcedureService (which tracks user-source mappings in _user_sources).

Resolve Session: Check ProcedureService for an active external_session_id for that user.

Call Memory Service: Send the question to the Memory Service (/agent/assist). This handles the requirement to allow questions even if no session is active (ambient questions).

Python

# Conceptual logic in AgentService._on_question_asked
# (Requires imports: procedure_service, logger, Event, EventType, httpx, settings)

async def _on_question_asked(self, event: Event):
    source_id = event.source_id
    question_text = event.payload.get("question")

    # 1. Resolve User
    username = None
    # Accessing _user_sources from procedure_service
    for user, src in procedure_service._user_sources.items():
        if src == source_id:
            username = user
            break
    
    if not username:
        logger.warning(f"Could not map source_id {source_id} to a username. Using source_id as fallback.")
        username = source_id

    # 2. Resolve Session
    session_id = None
    sessions = procedure_service._active_sessions.get(username)
    if sessions and sessions[0].external_session_id:
        session_id = sessions[0].external_session_id
        logger.info(f"Found active session {session_id} for user {username}.")
    else:
        # Crucial: Allows questions without an active session
        logger.info(f"No active session for user {username}. Sending ambient question.")

    # 3. Call Memory Service
    payload = {
        "query": question_text,
        "username": username,
        "session_id": session_id
    }
    await self.call_memory_agent(payload)

async def call_memory_agent(self, payload: dict):
    # (HTTP POST logic to Memory Service /agent/assist)
    # ...
5. Updates to Existing Files
A. app/domain/entities.py

Add the new event type to EventType.

Python

class EventType(str, Enum):
    # ... existing events ...
    QUESTION_ASKED = "question.asked"
B. requirements.txt

Add the required Python libraries.

Plaintext

# Audio Processing
webrtcvad-wheels
vosk
# Choose one for Wake Word (example: OpenWakeWord)
openwakeword
# tflite-runtime or tensorflow-cpu (dependency for OpenWakeWord)
C. Dockerfile

Ensure system dependencies are present. FFmpeg is already there. If using specific audio libraries (like Porcupine), you might need others (e.g., libportaudio2).

D. app/main.py

Ensure the new AgentService is initialized by importing it, which automatically subscribes it to the EventBus.

Python

# app/main.py
# ...
from app.services.procedure_service import procedure_service
# Import the new AgentService to initialize it (Implementation pending)
# from app.services.agent_service import agent_service 

logger.info("Initialized new architecture services (..., Procedure, Agent)")
# ...
E. app/core/startup.py

Initialize the audio pipeline components when the application starts, utilizing the existing RTSP_STREAM_URL and STREAM_USERNAME.

Python

# app/core/startup.py
# ...
# (Imports for AudioStreamReader and AudioAnalyzer pending implementation)

async def run_startup_initialization():
    # ...
    # Initialize Audio Analyzer models (New - Implementation Pending)
    # await audio_analyzer.initialize_models()

    if settings.RTSP_STREAM_URL:
        source_id = settings.STREAM_USERNAME or "default_camera"
        
        # ... (existing video reader start) ...
        
        # Start Audio Reader (New - Implementation Pending)
        # audio_reader = AudioStreamReader(source_id, settings.RTSP_STREAM_URL, audio_analyzer.process_chunk)
        # audio_reader.start()
        # _active_stream_readers.append(audio_reader) # Manage lifecycle
    # ...