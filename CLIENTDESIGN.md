# Smart Glasses Client Integration Guide

> How to build a client app (smart glasses, mobile, AR device) that works with Oneshot Copilot.

---

## Overview

Your smart glasses app needs to do 3 things:
1. **Stream video** to the copilot server
2. **Start/stop procedures** for a user  
3. **Poll for progress** and display instructions to the user

```
┌────────────────────────┐                    ┌─────────────────────────────┐
│    SMART GLASSES       │                    │    ONESHOT COPILOT          │
│                        │                    │    http://copilot:8000      │
│  ┌──────────────────┐  │                    │                             │
│  │  Camera Feed     │──┼── RTMP Stream ────▶│  Stream Reader              │
│  └──────────────────┘  │                    │       ↓                     │
│                        │                    │  AI Processing (automatic)  │
│  ┌──────────────────┐  │                    │       ↓                     │
│  │  Start/Stop UI   │──┼── HTTP REST ──────▶│  Procedure API              │
│  └──────────────────┘  │                    │       ↓                     │
│                        │                    │  State Machine              │
│  ┌──────────────────┐  │  ◀── HTTP Poll ────│       │                     │
│  │  Display/HUD     │  │                    │       ▼                     │
│  │  Instructions    │  │                    │  Status Endpoint            │
│  └──────────────────┘  │                    │                             │
└────────────────────────┘                    └─────────────────────────────┘
```

---

## 1. Streaming Video

### Setup RTMP Stream

The glasses must stream video via RTMP. The server automatically reads frames from the stream when a procedure is active.

**Server Configuration (`.env`):**
```env
RTSP_STREAM_URL=rtmp://192.168.1.100/live/glasses_stream
STREAM_USERNAME=glasses_user_001
```

**On the glasses:**
- Stream to: `rtmp://<copilot-ip>/live/<stream-key>`
- Format: H.264, 720p recommended
- Framerate: 15-30 FPS (server throttles to 5 FPS for AI)

> ⚠️ The stream must be running BEFORE starting a procedure. The server only reads frames during an active procedure session.

---

## 2. Discovering Available Procedures

Before starting a procedure, you can query which procedures are available on the server.

### HTTP Request

```
GET http://copilot:8000/api/v2/procedures/nodegraph/available
```

### Response

```json
{
  "strategy": "nodegraph",
  "procedures": [
    {
      "procedure_id": "proc_refill_dishwasher_salt",
      "title": "Refill Dishwasher Salt"
    },
    {
      "procedure_id": "proc_change_tire",
      "title": "Change a Flat Tire"
    }
  ]
}
```

### Usage

1. Call this endpoint on app startup or when the user opens a "procedure picker" UI
2. Display the `title` to the user
3. Use the corresponding `procedure_id` when calling the `/start` endpoint

> ⚠️ This endpoint only returns procedures compatible with the current strategy. If `PROCEDURE_STRATEGY=nodegraph`, only knowledge graph procedures are returned.

---

## 3. Starting a Procedure

When the user wants to begin a guided task (e.g., "Refill Dishwasher Salt"):

### HTTP Request

```
POST http://copilot:8000/api/v2/procedures/nodegraph/start
Content-Type: application/json

{
  "username": "glasses_user_001",
  "procedure_id": "proc_refill_dishwasher_salt",
  "source_id": "glasses_stream_001"
}
```

### Request Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `username` | Yes | Unique identifier for the user |
| `procedure_id` | Yes | ID of the procedure to start (from `/available` endpoint) |
| `source_id` | **Yes for new sessions** | The stream source ID registered when connecting your video stream |

> ⚠️ **Important:** The `source_id` is **required** when starting a procedure for the first time for a user. This links the user's session to the correct video stream. If omitted for a new session, you'll receive a `400 Bad Request` error:
> ```json
> {"detail": "Source ID is required for new session"}
> ```

### How to get a `source_id`

The `source_id` is automatically registered when your video stream connects to the copilot server. Common patterns:

1. **Use the stream key** - If your RTMP stream URL is `rtmp://copilot/live/glasses_stream_001`, then `glasses_stream_001` is your source_id
2. **Match your username** - Configure the same identifier for both stream and username for simplicity
3. **Check server logs** - When a stream connects, the server logs: `[INGEST] Registered source: <source_id>`

> 💡 **Tip:** Once a `source_id` is associated with a user, subsequent `/start` calls for the same user can omit it—the server remembers the mapping.

### Response

```json
{
  "status": "started",
  "username": "glasses_user_001",
  "procedure_id": "proc_refill_dishwasher_salt",
  "initial_node": {
    "id": "step_open_door",
    "title": "Open Dishwasher Door",
    "instruction": "Pull the handle and fully open the dishwasher door"
  }
}
```

### What happens on the server:
1. Loads the procedure definition from Memory Service
2. Starts reading frames from the RTMP stream
3. Begins sending frames to AI for visual verification
4. Polls AI results at 5Hz (automatic, no client action needed)

---

## 4. Polling for Progress

Once a procedure is started, poll the status endpoint to get the current step and display it to the user.

### HTTP Request

```
GET http://copilot:8000/api/v2/status?camera_id=glasses_user_001
```

### Response Examples

**Active Procedure:**
```json
{
  "username": "glasses_user_001",
  "state": "IN_PROGRESS",
  "procedure": "Refill Dishwasher Salt",
  "step": {
    "title": "Pour Salt",
    "instruction": "Pour salt into the reservoir until full"
  }
}
```

**Procedure Completed:**
```json
{
  "username": "glasses_user_001",
  "state": "COMPLETED",
  "procedure": "Refill Dishwasher Salt",
  "step": {
    "title": "Complete!",
    "instruction": "Salt reservoir has been refilled successfully."
  }
}
```

**No Active Procedure (Idle):**
```json
{
  "username": "glasses_user_001",
  "state": "IDLE",
  "procedure": null,
  "step": null
}
```

### Polling Loop (Recommended)

- **Polling interval:** 500ms - 1000ms
- **Display:** Show `step.title` and `step.instruction` on the HUD
- **Stop polling** when `state` is `IDLE` or `COMPLETED`

---

## 5. Stopping a Procedure

User cancels or procedure auto-completes:

### HTTP Request

```
POST http://copilot:8000/api/v2/procedures/nodegraph/stop
Content-Type: application/json

{
  "username": "glasses_user_001"
}
```

### Response

```json
{
  "status": "stopped",
  "username": "glasses_user_001"
}
```

> **Note:** Procedures auto-stop when they reach a `FINAL` node. You don't need to call stop manually unless the user cancels.

---

## 6. Detailed Progress (Optional)

For debugging or a detailed progress view:

### HTTP Request

```
GET http://copilot:8000/api/v2/procedures/nodegraph/status/glasses_user_001
```

### Response

```json
{
  "username": "glasses_user_001",
  "procedure_id": "proc_refill_dishwasher_salt",
  "procedure_title": "Refill Dishwasher Salt",
  "current_node": {
    "id": "step_pour_salt",
    "type": "ACTION",
    "title": "Pour Salt",
    "instruction": "Pour salt into the reservoir until full"
  },
  "validation_progress": 2,
  "action_timer_active": false,
  "inflight": true
}
```

| Field | Meaning |
|-------|---------|
| `validation_progress` | How many consecutive "correct" frames AI has seen (for stability) |
| `action_timer_active` | Is a timed action in progress (e.g., "pour for 5 seconds") |
| `inflight` | Is an AI request currently being processed |

---

## 7. Asking Questions (Agent Assist)

User can ask questions mid-procedure:

### HTTP Request

```
POST http://copilot:8000/api/v2/agent/assist
Content-Type: application/json

{
  "username": "glasses_user_001",
  "query": "How much salt should I pour?"
}
```

### Response

```json
{
  "answer": "Pour salt until the reservoir is full. The typical amount is about 1kg.",
  "confidence": 0.92
}
```

---

## Complete Client Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  GLASSES BOOT / APP LAUNCH                                                  │
│  ────────────────────────────────────────────────────────────────────────── │
│  1. Start RTMP stream to copilot server                                     │
│  2. Show "Ready" state on HUD                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    User says "Start refill dishwasher salt"
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  START PROCEDURE                                                            │
│  ────────────────────────────────────────────────────────────────────────── │
│  POST /api/v2/procedures/nodegraph/start                                    │
│  { "username": "...", "procedure_id": "proc_refill_dishwasher_salt" }       │
│                                                                              │
│  → Show first step: "Open Dishwasher Door"                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  POLLING LOOP (every 500ms)                                                 │
│  ────────────────────────────────────────────────────────────────────────── │
│  GET /api/v2/status?camera_id=...                                           │
│                                                                              │
│  Response state == "IN_PROGRESS"?                                           │
│     → Update HUD with step.title + step.instruction                         │
│     → Continue polling                                                       │
│                                                                              │
│  Response state == "COMPLETED"?                                             │
│     → Show "Done!" + step.instruction (success message)                     │
│     → Stop polling                                                          │
│                                                                              │
│  Response state == "IDLE"?                                                  │
│     → Procedure was stopped/cancelled                                       │
│     → Stop polling, return to ready state                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    User says "Stop" or procedure completes
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STOP PROCEDURE (if manual cancel)                                          │
│  ────────────────────────────────────────────────────────────────────────── │
│  POST /api/v2/procedures/nodegraph/stop                                     │
│  { "username": "..." }                                                       │
│                                                                              │
│  → Return to "Ready" state on HUD                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Sample Code (Python)

```python
import httpx
import asyncio

COPILOT_URL = "http://copilot-server:8000"
USERNAME = "glasses_user_001"

SOURCE_ID = "glasses_stream_001"  # Your registered stream source

async def start_procedure(procedure_id: str, source_id: str = None):
    async with httpx.AsyncClient() as client:
        payload = {"username": USERNAME, "procedure_id": procedure_id}
        if source_id:
            payload["source_id"] = source_id
        response = await client.post(
            f"{COPILOT_URL}/api/v2/procedures/nodegraph/start",
            json=payload
        )
        return response.json()

async def poll_status():
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{COPILOT_URL}/api/v2/status",
            params={"camera_id": USERNAME}
        )
        return response.json()

async def stop_procedure():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{COPILOT_URL}/api/v2/procedures/nodegraph/stop",
            json={"username": USERNAME}
        )
        return response.json()

async def run_procedure(procedure_id: str, source_id: str = None):
    # 1. Start (include source_id for first time users)
    result = await start_procedure(procedure_id, source_id)
    print(f\"Started: {result['initial_node']['title']}\")
    
    # 2. Poll loop
    while True:
        await asyncio.sleep(0.5)  # 500ms
        status = await poll_status()
        
        if status["state"] == "IN_PROGRESS":
            step = status["step"]
            print(f"📍 {step['title']}: {step['instruction']}")
        
        elif status["state"] == "COMPLETED":
            print(f"✅ Done! {status['step']['instruction']}")
            break
        
        elif status["state"] == "IDLE":
            print("⏹️ Procedure stopped")
            break

# Run (include SOURCE_ID for first-time users)
asyncio.run(run_procedure("proc_refill_dishwasher_salt", SOURCE_ID))
```

---

## Error Handling

| HTTP Code | Meaning | What to do |
|-----------|---------|------------|
| `200` | Success | Process response |
| `400` | Bad request | Check: (1) procedure_id exists, (2) source_id provided for new sessions |
| `404` | User/procedure not found | Start a procedure first |
| `500` | Server error | Retry or alert user |

**Example error response:**
```json
{
  "detail": "No active procedure for user"
}
```

---

## Checklist for Glasses App

- [ ] RTMP streaming working before procedure starts
- [ ] Can call `/start` endpoint and get initial step
- [ ] Polling loop updates HUD every 500ms
- [ ] HUD shows `step.title` and `step.instruction`
- [ ] Detect `COMPLETED` state and show success
- [ ] Stop button calls `/stop` endpoint
- [ ] Handle network errors gracefully
