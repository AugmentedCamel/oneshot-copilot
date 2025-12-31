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

## 2. Starting a Procedure

When the user wants to begin a guided task (e.g., "Refill Dishwasher Salt"):

### HTTP Request

```
POST http://copilot:8000/api/v2/procedures/nodegraph/start
Content-Type: application/json

{
  "username": "glasses_user_001",
  "procedure_id": "proc_refill_dishwasher_salt"
}
```

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

## 3. Polling for Progress

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

## 4. Stopping a Procedure

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

## 5. Detailed Progress (Optional)

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

## 6. Asking Questions (Agent Assist)

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

async def start_procedure(procedure_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{COPILOT_URL}/api/v2/procedures/nodegraph/start",
            json={"username": USERNAME, "procedure_id": procedure_id}
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

async def run_procedure(procedure_id: str):
    # 1. Start
    result = await start_procedure(procedure_id)
    print(f"Started: {result['initial_node']['title']}")
    
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

# Run
asyncio.run(run_procedure("proc_refill_dishwasher_salt"))
```

---

## Error Handling

| HTTP Code | Meaning | What to do |
|-----------|---------|------------|
| `200` | Success | Process response |
| `400` | Bad request | Check procedure_id exists |
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
