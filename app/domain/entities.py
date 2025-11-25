from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum
import time

@dataclass
class Source:
    id: str
    name: str
    type: str  # e.g., "camera", "glasses"
    ingest_type: str  # e.g., "rtmp", "webrtc"
    config: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Frame:
    id: str
    source_id: str
    timestamp_ms: int
    data: bytes  # Or path/reference to storage
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Job:
    id: str
    name: str
    source_id: str
    pipeline: List[Dict[str, Any]]  # List of steps (models, rules)
    outputs: List[Dict[str, Any]]   # Feedback, logs
    enabled: bool = True

@dataclass
class FeedbackChannel:
    id: str
    type: str  # e.g., "led", "audio", "screen"
    config: Dict[str, Any] = field(default_factory=dict)

class EventType(str, Enum):
    FRAME_CREATED = "frame.created"
    JOB_STARTED = "job.started"
    JOB_STOPPED = "job.stopped"
    MODEL_INFERENCE = "model.inference"
    RULE_TRIGGERED = "rule.triggered"
    FEEDBACK_SENT = "feedback.sent"
    ERROR = "error"
    # Legacy/Migration types
    STEP_STARTED = "step.started"
    STEP_PROGRESSED = "step.progressed"
    PROCEDURE_COMPLETED = "procedure.completed"

@dataclass
class Event:
    type: EventType
    job_id: Optional[str]
    source_id: Optional[str]
    payload: Dict[str, Any]
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    id: str = field(default_factory=lambda: str(time.time())) # Simple ID for now
