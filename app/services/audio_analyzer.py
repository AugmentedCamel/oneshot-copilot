import asyncio
import logging
import json
import numpy as np
import webrtcvad
from typing import Dict
from vosk import Model, KaldiRecognizer
from openwakeword.model import Model as OWWModel
from app.domain.entities import Event, EventType
from app.core.event_bus import event_bus

logger = logging.getLogger(__name__)

class StreamState:
    def __init__(self, sample_rate, vosk_model):
        self.state = "LISTENING"
        self.buffer = bytearray()
        self.silence_counter = 0
        self.rec = KaldiRecognizer(vosk_model, sample_rate)
        # Initialize OpenWakeWord per stream to maintain isolated state
        # Note: This might be heavy if many streams, but necessary for correctness
        self.oww_model = OWWModel(wakeword_models=["hey_jarvis"], inference_framework="tflite")

class AudioAnalyzer:
    def __init__(self):
        self.vad = None
        self.vosk_model = None
        
        # State per source_id
        self.streams: Dict[str, StreamState] = {}
        
        # Configuration
        self.sample_rate = 16000
        self.vad_frame_ms = 30
        self.vad_frame_size = int(self.sample_rate * self.vad_frame_ms / 1000 * 2) # 16000 * 0.03 * 2 = 960 bytes
        self.silence_threshold_chunks = 50 # Approx 1.5 seconds of silence (50 * 30ms = 1.5s)
        self.loop = None

    def set_loop(self, loop):
        self.loop = loop

    async def initialize_models(self):
        logger.info("Initializing AudioAnalyzer models...")
        
        # 1. VAD
        self.vad = webrtcvad.Vad(3) # Aggressiveness mode 3
        
        # 2. Wake Word
        try:
            import openwakeword
            openwakeword.utils.download_models()
        except Exception as e:
            logger.warning(f"Could not download openwakeword models: {e}")
            
        # We don't init OWWModel here anymore, we do it in StreamState
        
        # 3. STT (Vosk)
        try:
            self.vosk_model = Model(model_name="vosk-model-small-en-us-0.15")
        except Exception as e:
            logger.info("Downloading Vosk model...")
            raise e

        logger.info("AudioAnalyzer models initialized.")

    def get_stream_state(self, source_id: str) -> StreamState:
        if source_id not in self.streams:
            if not self.vosk_model:
                raise RuntimeError("AudioAnalyzer models not initialized")
            self.streams[source_id] = StreamState(self.sample_rate, self.vosk_model)
        return self.streams[source_id]

    def process_chunk(self, chunk: bytes, source_id: str):
        """
        Entry point for audio chunks from AudioStreamReader.
        """
        try:
            stream = self.get_stream_state(source_id)
            
            # Buffer for VAD frame size
            stream.buffer.extend(chunk)
            
            while len(stream.buffer) >= self.vad_frame_size:
                frame = bytes(stream.buffer[:self.vad_frame_size])
                stream.buffer = stream.buffer[self.vad_frame_size:]
                self._process_frame(frame, source_id, stream)
        except Exception as e:
            logger.error(f"Error processing audio chunk for {source_id}: {e}")

    def _process_frame(self, frame: bytes, source_id: str, stream: StreamState):
        # 1. VAD Check
        is_speech = self.vad.is_speech(frame, self.sample_rate)
        
        if stream.state == "LISTENING":
            # Feed to OpenWakeWord
            audio_data = np.frombuffer(frame, dtype=np.int16)
            prediction = stream.oww_model.predict(audio_data)
            
            # Check for wake word
            for md in stream.oww_model.prediction_buffer.keys():
                score = stream.oww_model.prediction_buffer[md][-1]
                if score > 0.5:
                    logger.warning(f"Wake word detected for {source_id}: {md} (Score: {score})")
                    stream.state = "TRANSCRIBING"
                    stream.silence_counter = 0
                    stream.rec.Reset()
                    # CRITICAL: Reset OWW model to clear history and prevent loops
                    stream.oww_model.reset()
                    break

        elif stream.state == "TRANSCRIBING":
            # Feed to Vosk
            if stream.rec.AcceptWaveform(frame):
                pass
            
            # Check for silence to end query
            if not is_speech:
                stream.silence_counter += 1
            else:
                stream.silence_counter = 0
                
            if stream.silence_counter > self.silence_threshold_chunks:
                logger.warning(f"Silence detected for {source_id}, finalizing transcription.")
                result = json.loads(stream.rec.FinalResult())
                text = result.get("text", "")
                
                if text:
                    logger.warning(f"Transcribed for {source_id}: {text}")
                    # Emit Event
                    event = Event(
                        type=EventType.QUESTION_ASKED,
                        job_id=None,
                        source_id=source_id,
                        payload={"question": text}
                    )
                    # We need to dispatch this async
                    if self.loop:
                        asyncio.run_coroutine_threadsafe(event_bus.publish(event), self.loop)
                    else:
                        logger.warning("Could not publish event: no event loop set")
                
                stream.state = "LISTENING"
                stream.silence_counter = 0

audio_analyzer = AudioAnalyzer()
