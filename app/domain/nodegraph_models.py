"""Domain models for Node Graph Procedure Strategy.

This module defines the data structures for state machine-based procedures
with node graphs, transitions, and AI-driven verification.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict


class NodeType(str, Enum):
    """Type of node in the procedure graph."""
    ACTION = "ACTION"
    RECOVERY = "RECOVERY"
    FINAL = "FINAL"


class VerificationMode(str, Enum):
    """How the AI verifies step completion."""
    VISUAL_STATE = "VISUAL_STATE"       # Static detection with stability frames
    ACTION_DURATION = "ACTION_DURATION"  # Timed action detection


@dataclass
class CortexConfig:
    """Configuration for AI verification of a node."""
    target_class: str                              # Class to detect (e.g., "door_fully_open")
    verification_mode: VerificationMode            # How to verify
    min_confidence: float                          # Minimum confidence threshold (0.0-1.0)
    stability_frames: Optional[int] = None         # For VISUAL_STATE: consecutive frames required
    duration_threshold_seconds: Optional[float] = None  # For ACTION_DURATION: seconds required
    excluded_candidates: List[str] = field(default_factory=list)  # Classes to exclude from AI scoring
    candidate_scope: List[str] = field(default_factory=list)  # Limit AI detection to only these classes


@dataclass
class ErrorHandler:
    """Error detection and fallback configuration."""
    trigger_class: str      # Class that triggers error (e.g., "error_spill_salt")
    fallback_node: str      # Node ID to transition to on error
    message: str            # Alert message to show user


@dataclass
class Transitions:
    """Transition configuration for a node."""
    on_success: Optional[str] = None   # Next node ID on successful completion
    on_timeout: Optional[str] = None   # Fallback node ID on timeout


@dataclass
class NodeUI:
    """UI configuration for a node."""
    title: str          # Human-readable step title
    instruction: str    # Instructions for the user


@dataclass
class NodeDef:
    """Definition of a single node in the procedure graph."""
    id: str                                        # Unique node identifier
    type: NodeType                                 # ACTION, RECOVERY, or FINAL
    ui: NodeUI                                     # UI configuration
    cortex_config: Optional[CortexConfig] = None   # AI verification config (None for FINAL)
    transitions: Optional[Transitions] = None      # Next node mappings
    error_handling: List[ErrorHandler] = field(default_factory=list)


@dataclass
class NodeGraphProcedureDef:
    """Definition of a node graph procedure."""
    procedure_id: str                    # Unique procedure identifier
    title: str                           # Human-readable title
    version: str                         # Version string
    initial_node_id: str                 # Starting node ID
    nodes: Dict[str, NodeDef]            # All nodes indexed by ID

    def get_node(self, node_id: str) -> Optional[NodeDef]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_initial_node(self) -> Optional[NodeDef]:
        """Get the initial node."""
        return self.get_node(self.initial_node_id)

    def get_all_target_classes(self, node_id: str) -> List[str]:
        """Get all target classes to check for a given node.
        
        Includes the main target_class and all error trigger_classes.
        """
        node = self.get_node(node_id)
        if not node:
            return []
        
        classes = []
        if node.cortex_config:
            classes.append(node.cortex_config.target_class)
        
        for handler in node.error_handling:
            classes.append(handler.trigger_class)
        
        return classes


@dataclass
class NodeGraphSession:
    """Session state for a node graph procedure execution."""
    username: str
    procedure: NodeGraphProcedureDef
    current_node_id: str                          # Current position in the graph
    validation_buffer: List[bool] = field(default_factory=list)  # For stability check
    action_timer_start: Optional[float] = None    # For ACTION_DURATION mode (timestamp)
    external_session_id: Optional[str] = None     # Memory service session ID
    inflight: bool = False                        # Is there a pending AI request?
    inflight_frame_id: Optional[str] = None       # Frame being processed
    last_frame_at_ms: Optional[int] = None        # Last frame timestamp
    # Control API fields
    auto_progress_enabled: bool = True            # When False, AI predictions don't trigger transitions
    visited_nodes: List[str] = field(default_factory=list)  # History of visited node IDs for "prev" navigation
    # AI Predictions for agent context (rolling buffer of last 3)
    latest_predictions: List[Dict] = field(default_factory=list)  # [{class: confidence}, ...]

    def get_current_node(self) -> Optional[NodeDef]:
        """Get the current node definition."""
        return self.procedure.get_node(self.current_node_id)

    def reset_validation_state(self) -> None:
        """Reset validation buffer and timer for a new node."""
        self.validation_buffer.clear()
        self.action_timer_start = None


def nodegraph_from_json(data: Dict) -> NodeGraphProcedureDef:
    """Parse a node graph procedure from JSON.
    
    Args:
        data: The procedure definition dict (from Memory Service 'definition' field)
        
    Returns:
        NodeGraphProcedureDef instance
    """
    nodes = {}
    
    for node_id, node_data in data.get("nodes", {}).items():
        # Parse node type
        node_type = NodeType(node_data.get("type", "ACTION"))
        
        # Parse UI
        ui_data = node_data.get("ui", {})
        ui = NodeUI(
            title=ui_data.get("title", ""),
            instruction=ui_data.get("instruction", "")
        )
        
        # Parse cortex config (optional for FINAL nodes)
        cortex_config = None
        cortex_data = node_data.get("cortex_config")
        if cortex_data:
            cortex_config = CortexConfig(
                target_class=cortex_data.get("target_class", ""),
                verification_mode=VerificationMode(cortex_data.get("verification_mode", "VISUAL_STATE")),
                min_confidence=cortex_data.get("min_confidence", 0.8),
                stability_frames=cortex_data.get("stability_frames"),
                duration_threshold_seconds=cortex_data.get("duration_threshold_seconds"),
                excluded_candidates=cortex_data.get("excluded_candidates", []),
                candidate_scope=cortex_data.get("candidate_scope", [])
            )
        
        # Parse transitions (optional for FINAL nodes)
        transitions = None
        trans_data = node_data.get("transitions")
        if trans_data:
            transitions = Transitions(
                on_success=trans_data.get("on_success"),
                on_timeout=trans_data.get("on_timeout")
            )
        
        # Parse error handlers
        error_handling = []
        for err_data in node_data.get("error_handling", []):
            error_handling.append(ErrorHandler(
                trigger_class=err_data.get("trigger_class", ""),
                fallback_node=err_data.get("fallback_node", ""),
                message=err_data.get("message", "")
            ))
        
        nodes[node_id] = NodeDef(
            id=node_id,
            type=node_type,
            ui=ui,
            cortex_config=cortex_config,
            transitions=transitions,
            error_handling=error_handling
        )
    
    return NodeGraphProcedureDef(
        procedure_id=data.get("procedure_id", ""),
        title=data.get("title", ""),
        version=data.get("version", "1.0"),
        initial_node_id=data.get("initial_node_id", ""),
        nodes=nodes
    )
