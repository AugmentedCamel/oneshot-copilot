# Node Graph Procedure Strategy

This document describes the Node Graph Procedure Strategy, a state machine-based approach for procedural workflows with visual state verification.

## Overview

Node Graph Procedures differ from linear step-by-step procedures by:
- **Node-based structure** with explicit transitions rather than a linear list
- **AI prediction vectors** that return confidence scores for multiple classes
- **Guard evaluation logic** with error handling priority, stability frames, and action duration modes
- **Two verification modes**: VISUAL_STATE (static detection) and ACTION_DURATION (timed actions)

## Architecture

```mermaid
flowchart LR
    subgraph Client
        Frontend[Frontend UI]
    end
    
    subgraph Copilot
        PS[Procedure Service]
        NGS[NodeGraph Strategy]
        NGE[NodeGraph Engine]
    end
    
    subgraph External
        MS[Memory Service]
        AI[AI Service]
    end
    
    Frontend -->|frames| PS
    PS --> NGS
    PS --> NGE
    NGS -->|GET /knowledge-graph/id| MS
    NGE -->|POST /stepnodedetection| AI
    AI -->|predictions| NGE
    NGE -->|transition events| PS
    PS -->|UI update| Frontend
```

## Procedure Definition Format

Knowledge graphs are stored in the Memory Service and fetched via:

```
GET /knowledge-graph/{procedure_id}
```

### Response Schema

```json
{
  "id": "resource-uuid",
  "procedure_id": "proc_refill_dishwasher_salt",
  "title": "Refill Dishwasher Salt",
  "definition": {
    "procedure_id": "proc_refill_dishwasher_salt",
    "title": "Refill Dishwasher Salt",
    "version": "1.0",
    "initial_node_id": "step_01_open_door",
    "nodes": { /* see Node Structure below */ }
  }
}
```

### Node Structure

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `ACTION`, `RECOVERY`, or `FINAL` |
| `ui.title` | string | Human-readable step title |
| `ui.instruction` | string | What the user should do |
| `cortex_config` | object | AI verification configuration |
| `transitions` | object | Next node mappings |
| `error_handling` | array | (Optional) Error triggers |

### Cortex Config

| Field | Type | Description |
|-------|------|-------------|
| `target_class` | string | Class for AI to detect (e.g., "door_fully_open") |
| `verification_mode` | string | `VISUAL_STATE` or `ACTION_DURATION` |
| `min_confidence` | float | Minimum confidence threshold (0.0-1.0) |
| `stability_frames` | int | Consecutive frames to confirm (VISUAL_STATE only) |
| `duration_threshold_seconds` | float | Action duration required (ACTION_DURATION only) |
| `excluded_candidates` | array | Classes to exclude from AI scoring (optional) |
| `candidate_scope` | array | Limit AI detection to only these classes (optional) |

---

## AI Service Contract

The AI node provides two modes of operation:

### Synchronous Mode (Legacy)

Used by the **Prompt Builder** for interactive testing.

```
POST /stepnodedetection
Content-Type: multipart/form-data
```

**Form Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `file` | binary | JPEG image frame |
| `user_id` | string | User identifier |
| `frame_id` | string | Unique frame identifier |
| `procedure_id` | string | Active procedure ID |
| `target_classes` | JSON array | Classes to check for (e.g., `["door_fully_open", "error_door_blocked"]`) |
| `excluded_candidates` | JSON array | Classes to exclude from scoring (optional) |
| `candidate_scope` | JSON array | Limit AI detection to only these classes (optional) |

**Response:**

```json
{
  "predictions": {
    "door_fully_open": 0.92,
    "error_door_blocked": 0.01,
    "rack_removed": 0.15
  }
}
```

---

### Asynchronous Mode (Knowledge Graph Procedure)

Used by the **NodeGraph Procedure Service** for high-throughput operation.

#### POST /stepnode/ingest

Non-blocking frame submission. Returns 202 immediately.

```
POST /stepnode/ingest
Content-Type: multipart/form-data
```

**Form Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `file` | binary | JPEG image frame |
| `procedure_id` | string | Active procedure ID |
| `user_id` | string | User identifier |

**Response:** `202 Accepted` (no body)

#### GET /stepnode/result

Poll for the latest detection result.

```
GET /stepnode/result
```

**Response (200 OK):**

```json
{
  "sequence_id": 6,
  "timestamp": 1735049000.123,
  "model_version": "vqa_wrapper_v1",
  "predictions": {"door_fully_open": 0.85, "rack_removed": 0.12},
  "timings": {...},
  "_buffer_metadata": {
    "procedure_id": "proc_dishwasher",
    "inference_ms": 147,
    "processed_at": "2024-12-24T15:40:00Z"
  }
}
```

**HTTP Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Success, result returned |
| 404 | No results available yet (first call before any inference) |
| 408 | Timeout waiting for a new result |

#### GET /stepnode/stats

Get buffer statistics for monitoring.

```
GET /stepnode/stats
```

**Response:**

```json
{
  "frames_written": 1234,
  "frames_overwritten": 56,
  "frames_processed": 1178,
  "buffer_size": 1
}
```

---

### Async Architecture

```mermaid
sequenceDiagram
    participant FS as Frame Source
    participant NGS as NodeGraphService
    participant AI as AI Node
    
    Note over NGS: Polling loop @ 5Hz
    
    FS->>NGS: Frame arrives
    NGS->>AI: POST /stepnode/ingest (202)
    
    loop Every 200ms
        NGS->>AI: GET /stepnode/result
        AI-->>NGS: latest predictions
        NGS->>NGS: evaluate_guards()
    end
```

---

## Execution Logic (State Machine)

### Step A: Context Lookup

1. Get `current_node_id` from session state
2. Look up node definition in cached knowledge graph
3. Extract `cortex_config` for this node:
   - `target_class` - what to detect
   - `verification_mode` - how to verify
   - `min_confidence` - threshold

### Step B: AI Interrogation

1. Collect all relevant classes for the current node:
   - `target_class` from `cortex_config`
   - `trigger_class` from each `error_handling` entry
2. Send frame + context to AI service
3. Receive prediction vector

### Step C: Guard Evaluation (Critical Logic)

**Priority 1: Check Errors (Safety First)**

```python
for error in node.error_handling:
    if predictions[error.trigger_class] > threshold:
        # Immediate transition to fallback
        transition_to(error.fallback_node)
        send_alert(error.message)
        return
```

**Priority 2: Check Success**

**VISUAL_STATE Mode:**
```python
score = predictions[target_class]
if score >= min_confidence:
    validation_buffer.append(True)
else:
    validation_buffer.clear()  # Strict reset

if validation_buffer.count(True) >= stability_frames:
    trigger_transition(on_success)
```

**ACTION_DURATION Mode:**
```python
score = predictions[target_class]
if score >= min_confidence:
    if action_timer_start is None:
        action_timer_start = now()
    elif (now() - action_timer_start) >= duration_threshold:
        trigger_transition(on_success)
else:
    action_timer_start = None  # Reset timer
```

### Step D: Transition Execution

When a transition is triggered:

1. Update `current_node_id` to the target node
2. Clear `validation_buffer`
3. Reset `action_timer_start` to None
4. Return new node's UI data to frontend immediately

---

## Configuration

Enable the node graph strategy in your `.env`:

```env
PROCEDURE_STRATEGY=nodegraph
AI_NODE_URL=http://localhost:8080
MEMORY_SERVICE_URL=http://localhost:8040
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/procedures/nodegraph/start` | POST | Start a node graph procedure |
| `/api/v2/procedures/nodegraph/stop` | POST | Stop the active procedure |
| `/api/v2/procedures/nodegraph/status/{username}` | GET | Get current node status |
| `/api/v2/procedures/nodegraph/debug` | GET | Debug all active sessions |

---

## Session State

The Node Graph Session tracks:

| Field | Type | Description |
|-------|------|-------------|
| `current_node_id` | string | Cursor position in the graph |
| `validation_buffer` | List[bool] | Recent detection results |
| `action_timer_start` | float | Timer start for ACTION_DURATION |
| `external_session_id` | string | Memory service session ID |

---

## Example Procedure

```json
{
  "procedure_id": "proc_refill_dishwasher_salt",
  "title": "Refill Dishwasher Salt",
  "version": "1.0",
  "initial_node_id": "step_01_open_door",
  "nodes": {
    "step_01_open_door": {
      "type": "ACTION",
      "ui": {
        "title": "Open Dishwasher",
        "instruction": "Pull the dishwasher door completely open."
      },
      "cortex_config": {
        "target_class": "door_fully_open",
        "verification_mode": "VISUAL_STATE",
        "min_confidence": 0.85,
        "stability_frames": 5
      },
      "transitions": {
        "on_success": "step_02_remove_rack",
        "on_timeout": "fallback_assist_door"
      }
    },
    "step_05_pour_salt": {
      "type": "ACTION",
      "ui": {
        "title": "Pour Salt",
        "instruction": "Pour dishwasher salt into the funnel until full."
      },
      "cortex_config": {
        "target_class": "pouring_salt_action",
        "verification_mode": "ACTION_DURATION",
        "duration_threshold_seconds": 5.0,
        "min_confidence": 0.75
      },
      "error_handling": [
        {
          "trigger_class": "error_spill_salt",
          "fallback_node": "fallback_wipe_spill",
          "message": "Salt spill detected! Please clean up."
        }
      ],
      "transitions": {
        "on_success": "step_06_remove_funnel"
      }
    },
    "end_procedure_complete": {
      "type": "FINAL",
      "ui": {
        "title": "Procedure Complete",
        "instruction": "Dishwasher is ready."
      }
    }
  }
}
```

---

## Related Files

| File | Purpose |
|------|---------|
| `app/domain/nodegraph_models.py` | Domain models |
| `app/domain/nodegraph_engine.py` | State machine logic |
| `app/services/nodegraph_strategy.py` | Procedure strategy |
| `app/core/nodegraph_client.py` | AI service client |
| `app/config.py` | Configuration |
