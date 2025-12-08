from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class DomainEvent:
    username: str

@dataclass
class StepStarted(DomainEvent):
    procedure_id: str
    step_id: int
    step_name: str

@dataclass
class StepProgressed(DomainEvent):
    procedure_id: str
    from_step: int
    to_step: int

@dataclass
class ProcedureCompleted(DomainEvent):
    procedure_id: str
    final_step: int

@dataclass
class VLMDispatchNeeded(DomainEvent):
    frame_id: str
    procedure_id: str
    step_def: Dict[str, Any]
    idem_key: str
    debug: bool

@dataclass
class FeedbackNeeded(DomainEvent):
    message: str
    step_id: int
    procedure_id: str

@dataclass
class StatusChanged(DomainEvent):
    pass

@dataclass
class VLMResponseReceived(DomainEvent):
    timestamp: str
    vlm_goal: str
    vlm_raw_answer: str
    bounding_boxes_detected: int
    bounding_box_items: str
    progress_decision: str
    procedure_id: str
    session_id: str
