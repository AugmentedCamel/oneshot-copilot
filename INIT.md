# ONESHOT COPILOT - COMPREHENSIVE SYSTEM DOCUMENTATION

> **A Vision-Driven AI Copilot Engine for Edge Deployment**
>
> Connect cameras with AI services and memory to create intelligent, real-time guidance systems for tasks, quality checking, and logging.

---

## TABLE OF CONTENTS

1. [Vision & Goals](#vision--goals)
2. [System Overview](#system-overview)
3. [Architecture](#architecture)
4. [Core Concepts](#core-concepts)
5. [Procedures System](#procedures-system)
6. [AI Integration](#ai-integration)
7. [Memory System](#memory-system)
8. [Camera Integration](#camera-integration)
9. [Smart Glasses Client](#smart-glasses-client)
10. [Creating New Procedures](#creating-new-procedures)
11. [Extending the System](#extending-the-system)
12. [Deployment Strategy](#deployment-strategy)
13. [Development Workflow](#development-workflow)
14. [Troubleshooting](#troubleshooting)

---

## VISION & GOALS

### What is Oneshot Copilot?

Oneshot Copilot is a **fully working copilot engine** designed to run on edge GPUs (laptops now, RTX 3090 or similar for mobile deployment in the future). It's a **sandbox connecting cameras with AI services and memory** to create intelligent, context-aware guidance systems.

### The Vision

**Current State:**
- Runs on laptops with edge GPUs
- Connects RTSP/RTMP cameras or smart glasses
- Uses Vision-Language-Action (VLA) models for visual understanding
- Provides real-time guidance through procedures

**Future State:**
- Deploy on mobile edge GPUs (RTX 3090, Jetson Xavier)
- Fully portable AI copilot system
- Run multiple procedures simultaneously
- Support diverse use cases: task assistance, quality control, logging, monitoring

### Core Use Cases

1. **Task Assistance** - Guide users through complex multi-step procedures
   - Examples: Assembling furniture, cooking recipes, repair tasks

2. **Quality Checking** - Verify that steps are completed correctly
   - Examples: Manufacturing QC, safety compliance checks

3. **Logging & Documentation** - Automatically document actions and events
   - Examples: Maintenance logs, inventory tracking, incident recording

4. **Real-time Monitoring** - Detect issues and provide alerts
   - Examples: Safety violations, equipment failures, anomaly detection

---

## SYSTEM OVERVIEW

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           ONESHOT COPILOT                                 │
│                        (Edge GPU - Laptop/RTX 3090)                       │
└──────────────────────────────────────────────────────────────────────────┘

┌────────────────────┐         ┌──────────────────────────────────────────┐
│  INPUT SOURCES     │         │          COPILOT ENGINE                   │
│                    │         │                                           │
│  • Smart Glasses   ├────────▶│  ┌─────────────────────────────────┐    │
│  • RTSP Cameras    │  Video  │  │   NodeGraph State Machine       │    │
│  • RTMP Streams    │  Frames │  │   • Context Lookup              │    │
│  • Manual Upload   │         │  │   • Guard Evaluation            │    │
└────────────────────┘         │  │   • Transition Logic            │    │
                               │  └─────────────────────────────────┘    │
┌────────────────────┐         │                                           │
│  AI SERVICES       │         │  ┌─────────────────────────────────┐    │
│                    │◀───────▶│  │   AI Integration Layer          │    │
│  • VLM/VLA Models  │  Async  │  │   • Connection Pooling          │    │
│  • Local/Cloud     │ Request │  │   • Aspect Ratio Normalization  │    │
│  • Moondream API   │ Callback│  │   • Callback Handler            │    │
└────────────────────┘         │  └─────────────────────────────────┘    │
                               │                                           │
┌────────────────────┐         │  ┌─────────────────────────────────┐    │
│  MEMORY SERVICE    │◀───────▶│  │   Memory Integration            │    │
│                    │         │  │   • Procedure Definitions       │    │
│  • Knowledge Graph │         │  │   • Session Management          │    │
│  • Procedures      │         │  │   • Context Retrieval           │    │
│  • Session State   │         │  └─────────────────────────────────┘    │
└────────────────────┘         │                                           │
                               │  ┌─────────────────────────────────┐    │
┌────────────────────┐         │  │   Event Bus (Pub/Sub)           │    │
│  OUTPUT CHANNELS   │◀────────┤  │   • Frame Events                │    │
│                    │ Feedback│  │   • State Transitions           │    │
│  • SSE Streams     │         │  │   • Error Events                │    │
│  • HTTP Callbacks  │         │  └─────────────────────────────────┘    │
│  • WebSockets      │         │                                           │
│  • TTS/Audio       │         │  ┌─────────────────────────────────┐    │
└────────────────────┘         │  │   Frame Processing              │    │
                               │  │   • Quality Control (blur/dark) │    │
                               │  │   • Rate Limiting (20 FPS)      │    │
                               │  │   • Frame Store                 │    │
                               │  └─────────────────────────────────┘    │
                               └──────────────────────────────────────────┘
```

### Technology Stack

**Backend:**
- FastAPI (async web framework)
- Python 3.8+
- OpenCV (video processing)
- httpx (async HTTP client)
- Uvicorn (ASGI server)

**AI Services:**
- Vision-Language-Action (VLA) models
- Local VLM providers (Auki, Moondream)
- Cloud VLM APIs (Moondream AI)

**Frontend/Client:**
- MentraApp (Smart glasses client)
- Node.js/TypeScript + Express
- Mentra SDK for AR glasses
- EJS templating

**Infrastructure:**
- Docker (containerization)
- MediaMTX (RTSP/RTMP streaming)
- External Memory Service (knowledge graphs)

**Audio:**
- Vosk (speech recognition)
- OpenWakeword (wake word detection)

---

## ARCHITECTURE

### Architectural Pattern: Event-Driven Domain Architecture

The system follows a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │   REST     │  │    SSE     │  │  WebSocket │            │
│  │  Endpoints │  │   Events   │  │  Streams   │            │
│  └────────────┘  └────────────┘  └────────────┘            │
│  app/api/ - FastAPI routes                                  │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                        │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │ NodeGraph Service│  │ Ingest Service   │                │
│  └──────────────────┘  └──────────────────┘                │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │ Feedback Service │  │ Agent Service    │                │
│  └──────────────────┘  └──────────────────┘                │
│  app/services/ - Orchestration & coordination               │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      DOMAIN LAYER                            │
│  ┌────────────────────────────────────────┐                 │
│  │      NodeGraph Engine (State Machine)  │                 │
│  │  - Context Lookup                      │                 │
│  │  - Guard Evaluation                    │                 │
│  │  - Transition Logic                    │                 │
│  └────────────────────────────────────────┘                 │
│               ┌──────────────┐                               │
│               │  Event Bus   │ (Pub/Sub)                    │
│               └──────────────┘                               │
│  app/domain/ - Business logic & state machines              │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   INFRASTRUCTURE LAYER                       │
│  ┌───────────┐  ┌───────────┐  ┌──────────┐                │
│  │  AI Node  │  │  Memory   │  │  Frame   │                │
│  │  Client   │  │  Service  │  │  Store   │                │
│  └───────────┘  └───────────┘  └──────────┘                │
│  app/core/ - Low-level services & adapters                  │
└─────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
oneshot-copilot-clean/
├── app/                          # Main application (7,870 lines Python)
│   ├── main.py                   # FastAPI entry point
│   ├── config.py                 # Configuration & settings
│   │
│   ├── api/                      # REST API endpoints
│   │   ├── nodegraph_v2.py       # NodeGraph procedure API
│   │   ├── vlm_callback.py       # AI callback handlers
│   │   ├── ingest_v2.py          # Frame ingestion
│   │   ├── procedure_control.py  # Manual control API
│   │   ├── events.py             # SSE endpoints
│   │   └── agent.py              # Agent Q&A
│   │
│   ├── services/                 # Application services
│   │   ├── nodegraph_service.py  # Main orchestrator (769 lines)
│   │   ├── ingest_service.py     # Frame ingestion coordinator
│   │   ├── stream_reader.py      # RTSP/RTMP reader (20 FPS)
│   │   ├── feedback_service.py   # Multi-channel feedback
│   │   ├── memory_service_client.py  # Memory integration
│   │   └── agent_service.py      # AI-powered Q&A
│   │
│   ├── domain/                   # Business logic & entities
│   │   ├── nodegraph_engine.py   # State machine (427 lines)
│   │   ├── nodegraph_models.py   # Data structures (204 lines)
│   │   ├── entities.py           # Domain entities
│   │   ├── events.py             # Domain events
│   │   └── interfaces.py         # Abstract interfaces
│   │
│   ├── core/                     # Infrastructure services
│   │   ├── event_bus.py          # Pub/sub event system
│   │   ├── nodegraph_client.py   # AI HTTP client (351 lines)
│   │   ├── frame_store.py        # Frame storage
│   │   ├── quality_control.py    # Frame quality analysis
│   │   ├── aspect_ratio.py       # Image normalization
│   │   └── startup.py            # App initialization
│   │
│   ├── models/                   # Data models
│   │   ├── state.py              # State enums
│   │   ├── procedure.py          # Procedure models
│   │   └── rules.py              # Rule models
│   │
│   └── data/                     # Runtime data
│       ├── procedures/           # Procedure JSON files
│       ├── user_status/          # User state persistence
│       └── frames/               # Frame storage
│
├── MentraApp/                    # Smart glasses client (Node.js)
│   ├── src/
│   │   ├── index.ts              # Main entry point
│   │   ├── webview.ts            # WebView management (32KB)
│   │   ├── tools.ts              # Mentra SDK integration
│   │   └── services/
│   │       ├── AudioFeedback.ts  # TTS audio feedback
│   │       └── UserMetadataService.ts
│   ├── views/                    # EJS templates
│   ├── public/css/               # Stylesheets
│   └── package.json              # Dependencies
│
├── docs/                         # Documentation
│   ├── NODEGRAPH_PROCEDURE.md    # NodeGraph system guide
│   ├── CLIENTDESIGN.md           # Smart glasses integration
│   ├── ANDROID_SSE_GUIDE.md      # SSE for Android
│   └── plugins.md                # Plugin system
│
├── tests/                        # Test suite
│   ├── test_procedure_control.py
│   ├── test_procedure_flow.py
│   └── test_bounding_box_fix.py
│
├── data_lake/                    # Training data for LoRA
├── archive/                      # Legacy code
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Container configuration
├── .env.example                  # Environment template
└── README.md                     # Quick start guide
```

### Data Flow

#### 1. Frame Ingestion Flow

```
┌─────────────┐
│ RTSP Stream │ or Smart Glasses Camera
└──────┬──────┘
       │ 30 FPS video
       ▼
┌──────────────────┐
│  StreamReader    │ • Read frames from RTSP
│  (20 FPS cap)    │ • Quality filter (blur/brightness)
└──────┬───────────┘
       │ 20 FPS clean frames
       ▼
┌──────────────────┐
│ IngestService    │ • Register frame source
│                  │ • Store frame data
│                  │ • Generate frame_id
└──────┬───────────┘
       │ Emit FRAME_CREATED event
       ▼
┌──────────────────┐
│   Event Bus      │ • Pub/sub decoupling
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ NodeGraphService │ • Check active sessions
│                  │ • Match frame to user
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ NodeGraphEngine  │ • Get current node
│                  │ • Prepare AI dispatch
│                  │ • Throttle to 20 FPS
└──────┬───────────┘
       │ Emit DISPATCH_NEEDED event
       ▼
┌──────────────────┐
│ NodeGraphClient  │ • Connection pooling
│ (AI HTTP Client) │ • Aspect ratio normalize
│                  │ • POST /stepnode/ingest
└──────┬───────────┘
       │ 202 Accepted (async)
       ▼
┌──────────────────┐
│  AI Node (VLA)   │ • Batch processing
│  External GPU    │ • 3-5 second latency
└──────────────────┘
```

#### 2. AI Callback Flow (Result Delivery)

```
┌──────────────────┐
│  AI Node (VLA)   │ Processing complete
└──────┬───────────┘
       │ POST /api/vlm/vla_callback
       ▼
┌──────────────────┐
│  VLM Callback    │ • Parse predictions
│  Handler         │ • Validate session_id
│  (API Layer)     │ • Extract confidence scores
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ NodeGraphService │ • Lookup session
│                  │ • Call engine.evaluate_guards()
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ NodeGraphEngine  │ GUARD EVALUATION LOGIC
│                  │ Priority 1: Check errors (safety)
│                  │ Priority 2: Check success
│                  │ • VISUAL_STATE: stability frames
│                  │ • ACTION_DURATION: timer duration
└──────┬───────────┘
       │
       ├─▶ Error Detected?
       │   └─▶ Transition to fallback node
       │       Send alert to user
       │
       └─▶ Success Criteria Met?
           └─▶ Transition to next node
               Update session state
               Clear validation buffer
               ▼
┌──────────────────┐
│ Feedback Service │ • SSE stream
│                  │ • HTTP callback
│                  │ • Audio TTS
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  Smart Glasses   │ Display new instruction
│  or Client       │ Play audio feedback
└──────────────────┘
```

---

## CORE CONCEPTS

### 1. Procedures

**What are procedures?**
Procedures are structured workflows that guide users through multi-step tasks. Each procedure is a directed graph of nodes representing steps.

**Types of Procedures:**
- **NodeGraph Procedures** (Current, Recommended) - State machine-based with explicit transitions
- **Linear Procedures** (Legacy) - Simple sequential steps

**Procedure Storage:**
- **Local JSON** - Stored in `app/data/procedures/`
- **Memory Service** - Fetched from external knowledge graph service
- **Hybrid** - Mix of local and external

### 2. NodeGraph State Machine

The **NodeGraphEngine** implements a formal state machine with 4 phases:

#### **Step A: Context Lookup**
```python
# Get current node and its configuration
node = session.get_current_node()
cortex_config = node.cortex_config
```

#### **Step B: AI Interrogation Preparation**
```python
# Collect all classes to detect
target_classes = [
    cortex_config.target_class,        # Main success class
    *[handler.trigger_class for handler in node.error_handling]  # Error classes
]

# Dispatch to AI service
dispatch_to_ai(frame, target_classes, excluded_candidates, candidate_scope)
```

#### **Step C: Guard Evaluation (Critical Logic)**

**Priority 1: Check Errors (Safety First)**
```python
for error_handler in node.error_handling:
    if predictions[error_handler.trigger_class] >= ERROR_THRESHOLD:
        # Immediate transition to fallback node
        transition_to(error_handler.fallback_node)
        send_alert(error_handler.message)
        return
```

**Priority 2: Check Success**

Two verification modes:

**VISUAL_STATE Mode** (Static detection with stability)
```python
if predictions[target_class] >= min_confidence:
    validation_buffer.append(True)
else:
    validation_buffer.clear()  # Strict reset

if len(validation_buffer) >= stability_frames:
    transition_to(on_success)
```

**ACTION_DURATION Mode** (Timed action detection)
```python
if predictions[target_class] >= min_confidence:
    if action_timer_start is None:
        action_timer_start = now()
    elif (now() - action_timer_start) >= duration_threshold:
        transition_to(on_success)
else:
    action_timer_start = None  # Reset timer
```

#### **Step D: Transition Execution**
```python
# Update session state
session.current_node_id = target_node_id
session.reset_validation_state()
session.validation_buffer.clear()
session.action_timer_start = None

# Emit events
emit(NodeGraphTransitionEvent(from_node, to_node, reason))
emit(StatusChanged(username))

# Check if new node is FINAL
if new_node.type == NodeType.FINAL:
    emit(NodeGraphCompletedEvent(procedure_id, final_node))
```

### 3. Node Types

**ACTION** - Regular procedural step requiring user action
```json
{
  "type": "ACTION",
  "ui": {
    "title": "Open Door",
    "instruction": "Pull the handle and open the door fully"
  },
  "cortex_config": { /* AI verification */ },
  "transitions": {
    "on_success": "next_step_id"
  }
}
```

**RECOVERY** - Error recovery step (fallback node)
```json
{
  "type": "RECOVERY",
  "ui": {
    "title": "Clean Spill",
    "instruction": "Wipe up the spilled salt"
  },
  "transitions": {
    "on_success": "return_to_main_flow"
  }
}
```

**FINAL** - Terminal node (procedure complete)
```json
{
  "type": "FINAL",
  "ui": {
    "title": "Complete",
    "instruction": "Task finished successfully!"
  }
}
```

### 4. Cortex Configuration (AI Verification)

The **cortex_config** defines how AI verifies step completion:

```json
{
  "target_class": "door_fully_open",
  "verification_mode": "VISUAL_STATE",
  "min_confidence": 0.85,
  "stability_frames": 5,
  "excluded_candidates": ["background", "irrelevant_object"],
  "candidate_scope": ["door_open", "door_closed", "door_partially_open"]
}
```

**Fields:**
- `target_class` - What to detect (e.g., "door_fully_open")
- `verification_mode` - How to verify: `VISUAL_STATE` or `ACTION_DURATION`
- `min_confidence` - Threshold (0.0-1.0)
- `stability_frames` - Consecutive frames for VISUAL_STATE (default: 5)
- `duration_threshold_seconds` - Duration for ACTION_DURATION (default: 3.0)
- `excluded_candidates` - Classes to exclude from AI scoring
- `candidate_scope` - Limit AI detection to only these classes

### 5. Error Handling

Error handlers provide safety and recovery:

```json
{
  "error_handling": [
    {
      "trigger_class": "error_spill_salt",
      "fallback_node": "recovery_clean_spill",
      "message": "Salt spilled! Please clean up before continuing."
    }
  ]
}
```

**Behavior:**
- Errors are checked **before** success (safety first)
- Error threshold: 0.7 (70% confidence)
- Immediate transition to fallback node
- Alert message sent to user

### 6. Transitions

Transitions define the directed graph structure:

```json
{
  "transitions": {
    "on_success": "step_02_next_action",
    "on_timeout": "fallback_help_user"
  }
}
```

---

## PROCEDURES SYSTEM

### Creating a NodeGraph Procedure

#### 1. Define the Procedure Structure

```json
{
  "procedure_id": "proc_make_coffee",
  "title": "Make Coffee",
  "version": "1.0",
  "initial_node_id": "step_01_fill_water",
  "nodes": {
    "step_01_fill_water": {
      "type": "ACTION",
      "ui": {
        "title": "Fill Water Tank",
        "instruction": "Fill the water tank to the MAX line"
      },
      "cortex_config": {
        "target_class": "water_tank_full",
        "verification_mode": "VISUAL_STATE",
        "min_confidence": 0.80,
        "stability_frames": 5
      },
      "error_handling": [
        {
          "trigger_class": "error_water_overflow",
          "fallback_node": "recovery_wipe_overflow",
          "message": "Water overflowed! Please wipe up excess water."
        }
      ],
      "transitions": {
        "on_success": "step_02_add_coffee",
        "on_timeout": "fallback_help_fill_water"
      }
    },
    "step_02_add_coffee": {
      "type": "ACTION",
      "ui": {
        "title": "Add Coffee Grounds",
        "instruction": "Add 2 scoops of coffee grounds to the filter"
      },
      "cortex_config": {
        "target_class": "coffee_grounds_added",
        "verification_mode": "VISUAL_STATE",
        "min_confidence": 0.75,
        "stability_frames": 3
      },
      "transitions": {
        "on_success": "step_03_press_brew"
      }
    },
    "step_03_press_brew": {
      "type": "ACTION",
      "ui": {
        "title": "Press Brew Button",
        "instruction": "Press and hold the brew button"
      },
      "cortex_config": {
        "target_class": "pressing_brew_button",
        "verification_mode": "ACTION_DURATION",
        "duration_threshold_seconds": 2.0,
        "min_confidence": 0.85
      },
      "transitions": {
        "on_success": "end_complete"
      }
    },
    "end_complete": {
      "type": "FINAL",
      "ui": {
        "title": "Coffee Ready!",
        "instruction": "Your coffee is brewing. Enjoy!"
      }
    },
    "recovery_wipe_overflow": {
      "type": "RECOVERY",
      "ui": {
        "title": "Clean Up",
        "instruction": "Wipe up the water overflow"
      },
      "cortex_config": {
        "target_class": "surface_clean",
        "verification_mode": "VISUAL_STATE",
        "min_confidence": 0.70,
        "stability_frames": 3
      },
      "transitions": {
        "on_success": "step_01_fill_water"
      }
    },
    "fallback_help_fill_water": {
      "type": "RECOVERY",
      "ui": {
        "title": "Need Help?",
        "instruction": "Locate the water tank on the back of the machine"
      },
      "transitions": {
        "on_success": "step_01_fill_water"
      }
    }
  }
}
```

#### 2. Save to Memory Service or Local File

**Option A: Memory Service** (Recommended for production)
1. POST to Memory Service: `POST /knowledge-graph/`
2. Procedure becomes available automatically
3. Can be updated without redeploying copilot

**Option B: Local JSON** (Good for development)
1. Save to `app/data/procedures/proc_make_coffee.json`
2. Restart server to load new procedure
3. Good for testing and iteration

#### 3. Test the Procedure

```bash
# 1. Start procedure
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/start \
  -H "Content-Type: application/json" \
  -d '{
    "username": "test_user",
    "procedure_id": "proc_make_coffee",
    "source_id": "test_camera"
  }'

# 2. Check status
curl http://localhost:8000/api/v2/procedures/nodegraph/status/test_user

# 3. Manual control (for testing)
# Disable auto-progression
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/control/auto_progress \
  -H "Content-Type: application/json" \
  -d '{"username": "test_user", "enabled": false}'

# Force next step
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/control/next \
  -H "Content-Type: application/json" \
  -d '{"username": "test_user"}'
```

### Procedure Design Best Practices

1. **Start Simple** - Begin with 3-5 nodes, expand later
2. **Clear Instructions** - Be specific and actionable
3. **Appropriate Confidence Thresholds** - Start with 0.75-0.85
4. **Stability Frames** - Use 3-5 for VISUAL_STATE
5. **Error Handling** - Add common failure cases
6. **Recovery Paths** - Provide help for stuck users
7. **Test Iteratively** - Use manual control to debug transitions

---

## AI INTEGRATION

### AI Service Architecture

The **NodeGraphClient** provides async communication with AI services:

#### Key Features

1. **Connection Pooling** - Persistent HTTP connections eliminate 300-700ms TCP handshake
2. **Aspect Ratio Normalization** - All frames converted to 16:9 landscape (AI training format)
3. **Async Callback Pattern** - Non-blocking frame ingestion with callback delivery
4. **Backpressure Control** - Semaphore limits concurrent requests (max 2)
5. **20 FPS Throttling** - Rate limiting to prevent AI overload

#### AI Service Endpoints

**POST /stepnode/ingest** (Async Mode)
```python
# Submit frame for processing (returns 202 immediately)
await client.ingest_frame_async(
    frame_bytes=frame_data,
    procedure_id="proc_make_coffee",
    user_id="test_user",
    target_classes=["water_tank_full", "error_water_overflow"],
    excluded_candidates=["background"],
    candidate_scope=["water_tank_empty", "water_tank_partial", "water_tank_full"]
)
```

**POST /api/vlm/vla_callback** (Result Delivery)
```json
{
  "username": "test_user",
  "session_id": "abc-123",
  "status": "IN_PROGRESS",
  "confidence": 0.75,
  "reasoning": "Water tank is filling but not yet at MAX line",
  "tts_message": "Keep filling, almost there!"
}
```

**Status Values:**
- `IRRELEVANT` - Frame doesn't relate to current step (very low confidence)
- `IN_PROGRESS` - User is working on step (low-moderate confidence)
- `COMPLETE` - Step completion criteria met (high confidence, triggers transition)
- `MISTAKE` - Error condition detected (triggers error handlers)

### VLM Providers

The system supports multiple VLM providers via strategy pattern:

```env
VLM_PROVIDER=auki_local  # Options: local, moondream, auki_local
VLM_URL=http://localhost:8080
MOONDREAM_API_KEY=your_key_here
```

**Auki Local** (Recommended for development)
- Runs on local GPU (Docker)
- Full control over model
- No rate limits
- Best latency

**Moondream AI** (Cloud option)
- No local GPU required
- Pay-per-use pricing
- Rate limited
- Good for prototyping

**Custom Local** (Advanced)
- Bring your own VLM
- Implement adapter in `app/core/vlm_strategies/`
- Full customization

---

## MEMORY SYSTEM

### Memory Service Integration

The **Memory Service** provides long-term knowledge graph storage:

#### Features

1. **Procedure Definitions** - Store and version procedures
2. **Session Management** - Track user sessions across restarts
3. **Context Retrieval** - Lookup past interactions for AI context
4. **Knowledge Graphs** - Structured procedure representations

#### Memory Service API

```python
# List available procedures
procedures = await memory_client.list_knowledge_graphs()
# Returns: [{"id": "...", "procedure_id": "...", "title": "..."}]

# Fetch procedure definition
knowledge_graph = await memory_client.get_knowledge_graph("proc_make_coffee")
# Returns: {"id": "...", "definition": {...nodes...}}

# Create session
session_id = await memory_client.create_session(
    username="test_user",
    procedure_id="proc_make_coffee",
    source_id="camera_01"
)

# Log event to session
await memory_client.add_item_to_session(
    session_id=session_id,
    content="User completed step: fill water tank",
    metadata={"confidence": 0.92, "node_id": "step_01"}
)

# Close session
await memory_client.close_session(session_id)
```

### Event Bus Architecture

The **EventBus** enables decoupled communication:

```python
# Subscribe to events
event_bus.subscribe(EventType.FRAME_CREATED, on_frame_handler)
event_bus.subscribe_all(log_all_events)

# Publish events
await event_bus.publish(Event(
    type=EventType.FRAME_CREATED,
    source_id="camera_01",
    payload={"frame": frame_object}
))

# Domain events
await event_bus.publish(NodeGraphTransitionEvent(
    username="test_user",
    procedure_id="proc_make_coffee",
    from_node="step_01",
    to_node="step_02",
    reason="success"
))
```

**Event Types:**
- `FRAME_CREATED` - New frame ingested
- `STATUS_CHANGED` - User state updated
- `NODE_TRANSITION` - Procedure advanced
- `NODE_COMPLETED` - Procedure finished
- `NODE_ERROR` - Error detected

---

## CAMERA INTEGRATION

### RTSP/RTMP Streaming

The **RtspStreamReader** handles video ingestion:

#### Features

1. **20 FPS Rate Limiting** - Consistent frame rate
2. **Quality Filtering** - Skip blurry or dark frames
3. **Automatic Reconnection** - Handles stream drops
4. **Async Frame Ingestion** - Non-blocking push to ingest service
5. **Buffer Management** - Minimal buffer size for low latency

#### Configuration

```env
RTSP_STREAM_URL=rtsp://192.168.2.7:8554/live/oneshot
STREAM_USERNAME=Mikameel
MAX_FRAMES_PER_USER=1
```

#### Quality Control

**FrameQualityAnalyzer** filters bad frames:

```python
is_good, reason = FrameQualityAnalyzer.is_frame_good(frame)

# Checks:
# 1. Laplacian variance > 100 (not blurry)
# 2. Mean brightness > 30 (not too dark)
# 3. Mean brightness < 250 (not overexposed)
```

**RateLimiter** enforces 20 FPS:

```python
rate_limiter = RateLimiter(fps=20.0)

if rate_limiter.should_process():
    process_frame(frame)
else:
    continue  # Skip this frame
```

### Aspect Ratio Normalization

All frames are normalized to **16:9 landscape** before AI processing:

```python
# app/core/aspect_ratio.py
frame_bytes = normalize_to_landscape_aspect_ratio(frame_bytes)

# Handles:
# - Portrait images → add black bars to sides
# - Square images → add black bars to top/bottom
# - Arbitrary aspect ratios → letterbox/pillarbox
# - Already 16:9 landscape → no change
```

**Why?** AI models are trained on 16:9 landscape images. Sending different aspect ratios degrades accuracy.

---

## SMART GLASSES CLIENT

### MentraApp Architecture

The **MentraApp** provides the smart glasses frontend:

#### Components

1. **Authentication** - Mentra OS user login
2. **Procedure Picker** - Browse available procedures
3. **Live HUD** - Display current step instructions
4. **Audio Feedback** - TTS for hands-free guidance
5. **SSE Stream** - Real-time agent replies
6. **RTMP Streamer** - Send camera feed to copilot

#### Client Integration Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  GLASSES BOOT / APP LAUNCH                                              │
│  ────────────────────────────────────────────────────────────────────  │
│  1. Start RTMP stream to copilot server                                 │
│  2. Connect SSE stream for agent replies                                │
│  3. Show "Ready" state on HUD                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    User says "Start make coffee"
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  DISCOVER PROCEDURES                                                    │
│  ────────────────────────────────────────────────────────────────────  │
│  GET /api/v2/procedures/nodegraph/available                             │
│  Response: [{"procedure_id": "proc_make_coffee", "title": "..."}]      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  START PROCEDURE                                                        │
│  ────────────────────────────────────────────────────────────────────  │
│  POST /api/v2/procedures/nodegraph/start                                │
│  { "username": "...", "procedure_id": "proc_make_coffee",               │
│    "source_id": "glasses_camera" }                                      │
│                                                                          │
│  → Show first step: "Fill Water Tank"                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  POLLING LOOP (every 500ms)                                             │
│  ────────────────────────────────────────────────────────────────────  │
│  GET /api/v2/status?camera_id=...                                       │
│                                                                          │
│  Response state == "IN_PROGRESS"?                                       │
│     → Update HUD with step.title + step.instruction                     │
│     → Continue polling                                                  │
│                                                                          │
│  Response state == "COMPLETED"?                                         │
│     → Show "Done!" + success message                                    │
│     → Play completion sound                                             │
│     → Stop polling                                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    User says "Stop" or procedure completes
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STOP PROCEDURE (if manual cancel)                                      │
│  ────────────────────────────────────────────────────────────────────  │
│  POST /api/v2/procedures/nodegraph/stop                                 │
│  { "username": "..." }                                                  │
│                                                                          │
│  → Return to "Ready" state on HUD                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### SSE for Real-Time Updates

**Server-Sent Events** provide instant agent replies:

```javascript
// Connect SSE stream
const eventSource = new EventSource(`http://copilot:8000/api/v2/events/${username}`);

eventSource.addEventListener('agent_reply', (event) => {
  const data = JSON.parse(event.data);
  displayToUser(data.text);  // Show on HUD
  speakText(data.text);       // TTS audio
});

eventSource.addEventListener('heartbeat', (event) => {
  console.log('Connection alive');
});
```

---

## CREATING NEW PROCEDURES

### Use Case: Quality Checking Procedure

Let's create a procedure for checking product quality:

```json
{
  "procedure_id": "proc_quality_check_widget",
  "title": "Widget Quality Check",
  "version": "1.0",
  "initial_node_id": "step_01_scan_barcode",
  "nodes": {
    "step_01_scan_barcode": {
      "type": "ACTION",
      "ui": {
        "title": "Scan Barcode",
        "instruction": "Point camera at widget barcode"
      },
      "cortex_config": {
        "target_class": "barcode_detected",
        "verification_mode": "VISUAL_STATE",
        "min_confidence": 0.90,
        "stability_frames": 3
      },
      "transitions": {
        "on_success": "step_02_inspect_surface"
      }
    },
    "step_02_inspect_surface": {
      "type": "ACTION",
      "ui": {
        "title": "Inspect Surface",
        "instruction": "Rotate widget slowly to show all surfaces"
      },
      "cortex_config": {
        "target_class": "surface_quality_good",
        "verification_mode": "ACTION_DURATION",
        "duration_threshold_seconds": 10.0,
        "min_confidence": 0.75
      },
      "error_handling": [
        {
          "trigger_class": "defect_scratch_detected",
          "fallback_node": "reject_defect_scratch",
          "message": "DEFECT: Scratch detected on surface"
        },
        {
          "trigger_class": "defect_crack_detected",
          "fallback_node": "reject_defect_crack",
          "message": "DEFECT: Crack detected on widget"
        }
      ],
      "transitions": {
        "on_success": "step_03_check_dimensions"
      }
    },
    "step_03_check_dimensions": {
      "type": "ACTION",
      "ui": {
        "title": "Check Dimensions",
        "instruction": "Place widget on measuring template"
      },
      "cortex_config": {
        "target_class": "dimensions_within_tolerance",
        "verification_mode": "VISUAL_STATE",
        "min_confidence": 0.85,
        "stability_frames": 5
      },
      "error_handling": [
        {
          "trigger_class": "dimensions_out_of_spec",
          "fallback_node": "reject_dimension_failure",
          "message": "DEFECT: Dimensions out of specification"
        }
      ],
      "transitions": {
        "on_success": "end_pass"
      }
    },
    "end_pass": {
      "type": "FINAL",
      "ui": {
        "title": "PASS",
        "instruction": "Widget passed quality check. Mark as PASS."
      }
    },
    "reject_defect_scratch": {
      "type": "FINAL",
      "ui": {
        "title": "REJECT - SCRATCH",
        "instruction": "Widget rejected due to surface scratch. Mark as REJECT."
      }
    },
    "reject_defect_crack": {
      "type": "FINAL",
      "ui": {
        "title": "REJECT - CRACK",
        "instruction": "Widget rejected due to crack. Mark as REJECT."
      }
    },
    "reject_dimension_failure": {
      "type": "FINAL",
      "ui": {
        "title": "REJECT - DIMENSIONS",
        "instruction": "Widget rejected due to dimension failure. Mark as REJECT."
      }
    }
  }
}
```

**Key Features:**
- Multiple error paths for different defect types
- ACTION_DURATION for thorough inspection
- High confidence thresholds for quality decisions
- Clear PASS/REJECT terminal nodes

---

## EXTENDING THE SYSTEM

### Adding a New VLM Provider

1. **Create Strategy Class**

```python
# app/core/vlm_strategies/my_custom_vlm.py
from typing import Dict, List
import httpx
from app.core.vlm_strategies.base import VLMStrategy

class MyCustomVLMStrategy(VLMStrategy):
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.AsyncClient()

    async def dispatch(
        self,
        frame_bytes: bytes,
        user_id: str,
        frame_id: str,
        procedure_id: str,
        target_classes: List[str]
    ) -> Dict[str, float]:
        """Send frame to custom VLM and return predictions."""

        response = await self.client.post(
            f"{self.base_url}/vision/analyze",
            files={"image": frame_bytes},
            data={
                "classes": ",".join(target_classes),
                "api_key": self.api_key
            }
        )

        result = response.json()

        # Convert to standard format
        predictions = {}
        for class_name in target_classes:
            predictions[class_name] = result["scores"].get(class_name, 0.0)

        return predictions
```

2. **Register in Config**

```python
# app/config.py
VLM_PROVIDER = "my_custom"  # Add new option

# app/core/vlm_strategies/__init__.py
from app.core.vlm_strategies.my_custom_vlm import MyCustomVLMStrategy

def get_vlm_strategy():
    if settings.VLM_PROVIDER == "my_custom":
        return MyCustomVLMStrategy(
            api_key=settings.MY_CUSTOM_API_KEY,
            base_url=settings.MY_CUSTOM_URL
        )
    # ... existing providers
```

3. **Update Environment**

```env
VLM_PROVIDER=my_custom
MY_CUSTOM_API_KEY=your_api_key
MY_CUSTOM_URL=https://api.mycustom.ai
```

### Adding a New Procedure Source

1. **Create Strategy Class**

```python
# app/services/database_procedure_strategy.py
from typing import List, Optional
from app.domain.nodegraph_models import NodeGraphProcedureDef, nodegraph_from_json

class DatabaseProcedureStrategy:
    def __init__(self, db_connection_string: str):
        self.db = connect_to_database(db_connection_string)

    async def load_procedure(self, procedure_id: str) -> NodeGraphProcedureDef:
        """Load procedure from SQL database."""
        row = await self.db.fetch_one(
            "SELECT definition FROM procedures WHERE id = ?",
            (procedure_id,)
        )
        definition = json.loads(row["definition"])
        return nodegraph_from_json(definition)

    async def list_procedures(self) -> List[Dict]:
        """List all available procedures."""
        rows = await self.db.fetch_all(
            "SELECT id, title FROM procedures WHERE active = 1"
        )
        return [
            {"procedure_id": row["id"], "title": row["title"]}
            for row in rows
        ]
```

2. **Register Strategy**

```python
# app/services/nodegraph_service.py
def get_procedure_strategy():
    if settings.PROCEDURE_STRATEGY == "database":
        return DatabaseProcedureStrategy(settings.DATABASE_URL)
    elif settings.PROCEDURE_STRATEGY == "nodegraph":
        return NodeGraphProcedureStrategy(memory_client)
    # ... etc
```

### Adding Custom Event Handlers

```python
# app/my_custom_handlers.py
from app.core.event_bus import event_bus
from app.domain.nodegraph_engine import NodeGraphTransitionEvent
import logging

logger = logging.getLogger(__name__)

async def log_transitions_to_database(event: NodeGraphTransitionEvent):
    """Log all transitions to database for analytics."""
    await db.execute(
        "INSERT INTO transition_log (username, procedure_id, from_node, to_node, reason, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (event.username, event.procedure_id, event.from_node, event.to_node, event.reason, time.time())
    )
    logger.info(f"Logged transition: {event.from_node} -> {event.to_node}")

# Register handler
event_bus.subscribe(NodeGraphTransitionEvent, log_transitions_to_database)
```

---

## DEPLOYMENT STRATEGY

### Current: Laptop Development

**Hardware:**
- Laptop with GPU (NVIDIA recommended)
- 8GB+ GPU VRAM for local VLM
- 16GB+ system RAM

**Software:**
```bash
# Python environment
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# VLM service (Docker)
cd vlm-node
make docker-gpu

# Copilot server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# MentraApp client
cd MentraApp
bun run dev
```

### Future: Mobile Edge GPU (RTX 3090)

**Target Hardware:**
- NVIDIA RTX 3090 (24GB VRAM)
- Jetson Xavier AGX (alternative)
- Portable power supply
- Compact form factor

**Deployment Architecture:**

```
┌──────────────────────────────────────────────────────────────┐
│              PORTABLE EDGE DEVICE (RTX 3090)                 │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Docker Container: Oneshot Copilot (Port 8000)        │ │
│  │  • FastAPI server                                      │ │
│  │  • Frame processing (20 FPS)                           │ │
│  │  • State machine engine                                │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Docker Container: AI Node (Port 8080) - GPU          │ │
│  │  • VLA model inference                                 │ │
│  │  • CUDA acceleration                                   │ │
│  │  • 3-5 second latency                                  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Docker Container: Memory Service (Port 8040)          │ │
│  │  • Knowledge graphs                                    │ │
│  │  • Procedure storage                                   │ │
│  │  • Session management                                  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Docker Container: MediaMTX (Ports 8554, 1935)        │ │
│  │  • RTSP/RTMP server                                    │ │
│  │  • Stream aggregation                                  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
└──────────────────────────────────────────────────────────────┘
                            │
                            │ WiFi/5G
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              SMART GLASSES / MOBILE CLIENTS                  │
│  • Mentra Glasses                                            │
│  • Android AR devices                                        │
│  • iOS AR devices                                            │
└──────────────────────────────────────────────────────────────┘
```

**Docker Compose (Production)**

```yaml
# docker-compose.yml
version: '3.8'

services:
  copilot:
    image: oneshot-copilot:latest
    ports:
      - "8000:8000"
    environment:
      - AI_NODE_URL=http://ai_node:8080
      - MEMORY_SERVICE_URL=http://memory:8040
      - RTSP_STREAM_URL=rtmp://mediamtx:1935/live/stream
    depends_on:
      - ai_node
      - memory
      - mediamtx
    restart: unless-stopped

  ai_node:
    image: auki/vlm-node:latest
    ports:
      - "8080:8080"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

  memory:
    image: memory-service:latest
    ports:
      - "8040:8040"
    volumes:
      - memory_data:/data
    restart: unless-stopped

  mediamtx:
    image: bluenviron/mediamtx:latest
    ports:
      - "8554:8554"  # RTSP
      - "1935:1935"  # RTMP
      - "8888:8888"  # Web UI
    restart: unless-stopped

volumes:
  memory_data:
```

**Deploy to Edge Device:**

```bash
# 1. Build images
docker compose build

# 2. Deploy stack
docker compose up -d

# 3. Verify
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8080/health

# 4. Monitor logs
docker compose logs -f copilot
```

### Scaling Considerations

**Multiple Procedures:**
- Run multiple procedures simultaneously (different users)
- NodeGraphService manages separate sessions per user
- No interference between sessions

**Multiple Cameras:**
- Register multiple RTSP/RTMP sources
- Each user mapped to their own camera feed
- Frame store handles concurrent streams

**Load Balancing:**
- Deploy multiple copilot instances
- Reverse proxy (Nginx/Traefik) for load balancing
- Shared Memory Service for state

---

## DEVELOPMENT WORKFLOW

### Setting Up Development Environment

```bash
# 1. Clone repository
git clone <repo-url>
cd oneshot-copilot-clean

# 2. Create Python virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your settings

# 5. Start VLM service (optional, for local AI)
cd vlm-node
make docker-gpu

# 6. Start copilot server (auto-reload for development)
cd oneshot-copilot-clean
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. Start MentraApp (in separate terminal)
cd MentraApp
cp .env.example .env
# Edit .env with Mentra credentials
bun install
bun run dev
```

### Testing a Procedure

```bash
# 1. List available procedures
curl http://localhost:8000/api/v2/procedures/nodegraph/available

# 2. Start a procedure
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/start \
  -H "Content-Type: application/json" \
  -d '{
    "username": "dev_user",
    "procedure_id": "proc_make_coffee",
    "source_id": "test_camera"
  }'

# 3. Disable auto-progression (for manual testing)
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/control/auto_progress \
  -H "Content-Type: application/json" \
  -d '{"username": "dev_user", "enabled": false}'

# 4. Manually upload test frames
curl -X POST http://localhost:8000/api/v2/ingest \
  -F "username=dev_user" \
  -F "frame_id=frame_001" \
  -F "file=@test_images/water_tank_full.jpg"

# 5. Manually advance to next node
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/control/next \
  -H "Content-Type: application/json" \
  -d '{"username": "dev_user"}'

# 6. Check current status
curl http://localhost:8000/api/v2/procedures/nodegraph/status/dev_user

# 7. Stop procedure
curl -X POST http://localhost:8000/api/v2/procedures/nodegraph/stop \
  -H "Content-Type: application/json" \
  -d '{"username": "dev_user"}'
```

### Debugging Tips

**1. Enable Verbose Logging**
```python
# app/config.py
VERBOSE_LOGGING = True
```

**2. Monitor Event Bus**
```python
# Add to app/main.py
event_bus.subscribe_all(lambda event: logger.debug(f"EVENT: {event}"))
```

**3. Check Frame Quality**
```python
# Test frame quality filters
from app.core.quality_control import FrameQualityAnalyzer
import cv2

frame = cv2.imread("test_image.jpg")
is_good, reason = FrameQualityAnalyzer.is_frame_good(frame)
print(f"Frame quality: {is_good}, reason: {reason}")
```

**4. Inspect AI Predictions**
```bash
# Check AI node logs
docker logs ai_node_container

# Test AI endpoint directly
curl -X POST http://localhost:8080/stepnodedetection \
  -F "file=@test_image.jpg" \
  -F "user_id=test" \
  -F "frame_id=test_001" \
  -F "procedure_id=proc_test" \
  -F 'target_classes=["water_tank_full", "coffee_grounds_added"]'
```

**5. Debug State Machine**
```python
# Add breakpoints in nodegraph_engine.py
# app/domain/nodegraph_engine.py line 168 (evaluate_guards)
import pdb; pdb.set_trace()
```

---

## TROUBLESHOOTING

### Common Issues

#### 1. AI Service Not Responding

**Symptoms:**
- Procedures don't progress
- Logs show "Connection failed" errors
- Timeout exceptions

**Solutions:**
```bash
# Check AI service is running
curl http://localhost:8080/health

# Verify connection from copilot
# app/config.py
AI_NODE_URL=http://localhost:8080  # Must be reachable

# Check Docker GPU access
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# Restart AI node
docker restart ai_node_container
```

#### 2. Frames Not Being Ingested

**Symptoms:**
- No frames appearing in logs
- RTSP stream configured but inactive

**Solutions:**
```bash
# Verify stream URL is correct
ffplay rtsp://192.168.2.7:8554/live/oneshot

# Check stream reader logs
# Look for: [STREAM_READER] Connected to RTSP stream

# Verify source registration
# Look for: [INGEST] Registered source: <source_id>

# Test manual frame ingestion
curl -X POST http://localhost:8000/api/v2/ingest \
  -F "username=test" \
  -F "frame_id=test_001" \
  -F "file=@test.jpg"
```

#### 3. Procedures Not Transitioning

**Symptoms:**
- Stuck on same node
- High confidence but no transition

**Solutions:**
```bash
# Check auto-progress is enabled
curl http://localhost:8000/api/v2/procedures/nodegraph/control/status?username=test

# Verify AI predictions
# Look for: [NODEGRAPH] Received predictions: {...}

# Check guard evaluation logs
# Look for: [NODEGRAPH] Evaluating guards for node

# Inspect validation buffer
# Look for: [NODEGRAPH] VISUAL_STATE: buffer has X/Y frames

# Lower confidence threshold temporarily
# In procedure JSON: "min_confidence": 0.70 (instead of 0.85)
```

#### 4. Memory Service Connection Issues

**Symptoms:**
- "Failed to load procedure" errors
- Timeout when fetching knowledge graphs

**Solutions:**
```bash
# Check Memory Service is running
curl http://localhost:8040/health

# Verify procedure exists
curl http://localhost:8040/knowledge-graph/proc_make_coffee

# Fall back to local JSON
# app/config.py
PROCEDURE_STRATEGY=local

# Or create local copy
cp memory_export.json app/data/procedures/proc_make_coffee.json
```

#### 5. Smart Glasses Not Connecting

**Symptoms:**
- Mentra app shows "disconnected"
- No video feed from glasses

**Solutions:**
```bash
# Check MentraApp is running
curl http://localhost:3000/health

# Verify RTMP server
curl http://localhost:8888  # MediaMTX web UI

# Test RTMP stream
ffmpeg -re -i test.mp4 -c copy -f flv rtmp://localhost:1935/live/test

# Check Mentra SDK configuration
# MentraApp/.env
MENTRAOS_API_KEY=your_key
PACKAGE_NAME=com.yourcompany.oneshotcopilot
```

---

## FINAL NOTES

### System Design Philosophy

1. **Edge-First** - Designed to run on portable GPUs
2. **Event-Driven** - Decoupled components via event bus
3. **Extensible** - Plugin architecture for VLMs, procedures, memory
4. **Production-Ready** - Connection pooling, backpressure, error handling
5. **Developer-Friendly** - Clear abstractions, comprehensive logging

### Future Enhancements

**Planned Features:**
- [ ] Multi-procedure parallel execution
- [ ] Real-time procedure editing without restart
- [ ] Advanced analytics dashboard
- [ ] Voice command integration
- [ ] Offline mode with sync-on-reconnect
- [ ] Gesture recognition for hands-free control
- [ ] Augmented reality overlay integration
- [ ] LoRA fine-tuning pipeline automation

**Optimization Opportunities:**
- Reduce AI latency (current: 3-5s, target: <1s)
- Increase frame throughput (current: 20 FPS, target: 30 FPS)
- Optimize memory usage for longer sessions
- Add frame batching for efficiency

### Contributing

When extending this system:
1. Follow the **layered architecture** pattern
2. Use the **event bus** for decoupled communication
3. Add **comprehensive logging** at DEBUG level
4. Write **unit tests** for domain logic
5. Update **documentation** (this file and others)
6. Test on **edge hardware** before deploying

### Support

- **Documentation**: `docs/` directory
- **Code Examples**: `tests/` directory
- **Issues**: GitHub Issues
- **Discussion**: GitHub Discussions

---

**Created by:** Mika Haak (@augmentedcamel)
**License:** MIT
**Last Updated:** 2026-01-05

---

This comprehensive guide covers the entire Oneshot Copilot system. For specific topics, refer to:
- `docs/NODEGRAPH_PROCEDURE.md` - NodeGraph procedures in detail
- `docs/CLIENTDESIGN.md` - Smart glasses client integration
- `docs/ANDROID_SSE_GUIDE.md` - SSE implementation for Android
- `README.md` - Quick start guide
