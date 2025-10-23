# Oneshot Copilot

A FastAPI-based copilot system that helps users complete procedures step-by-step using computer vision analysis.

## Overview

Oneshot Copilot guides users through multi-step procedures by analyzing video frames in real-time. It uses a VLM (Vision Language Model) service to verify each step's completion before allowing progression to the next step.

### Key Features

- **Step-by-step procedure guidance** with configurable steps
- **Real-time frame analysis** using VLM integration
- **Debounce logic** requiring multiple consecutive YES responses
- **Frame buffering** to handle high-frequency updates
- **Single in-flight request** per user to prevent overload
- **Timeout handling** with automatic reset
- **Client callbacks** for progress updates

## Architecture

```
Client → /ingest (frames) → State Machine → VLM Service
                                   ↓
Client ← Progress Updates ← State Machine ← /vlm/callback
```

## Installation

1. **Clone the repository**
```bash
cd oneshot_copilot
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your actual URLs
```

## Configuration

Edit `.env` file with your settings:

```env
SELF_URL=https://your-server.ngrok-free.app
MENTRA_URL=https://client-webhook.example.com
VLM_URL=https://vlm-service.ngrok.app
MAX_FRAMES_PER_USER=10

# Optional: RTSP/RTMP Stream Auto-Ingestion
RTSP_STREAM_URL=rtsp://192.168.1.100:8554/live/stream
STREAM_USERNAME=stream_user
```

### RTSP Stream Auto-Ingestion (Optional)

Oneshot Copilot can automatically ingest frames from an RTSP or RTMP stream. When configured, it will:
- Connect to the stream on application startup
- Filter frames by quality (blur and brightness)
- Automatically POST quality frames to the `/ingest` endpoint
- Send approximately 1 frame per second

To enable:
1. Set `RTSP_STREAM_URL` to your camera/stream URL
2. Set `STREAM_USERNAME` to identify frames from this stream
3. Restart the application

Leave `RTSP_STREAM_URL` empty to disable this feature.

### Moondream AI Cloud VLM Support

Oneshot Copilot supports both local and cloud-based VLM services. By default, it uses a local VLM service, but you can switch to Moondream AI cloud VLM for production deployments.

To use Moondream AI cloud VLM:

1. Sign up at [moondream.ai](https://moondream.ai) and get your API key
2. Set `USE_CLOUD_VLM=true` in `.env`
3. Set `MOONDREAM_API_KEY=your_key` in `.env`
4. See [CLOUD_VLM.md](CLOUD_VLM.md) for detailed documentation

**Configuration example:**
```env
USE_CLOUD_VLM=true
MOONDREAM_API_KEY=your_moondream_api_key_here
```

**Important Note**: Moondream AI cloud does not support negative questions. When using cloud VLM, only positive questions from procedures are sent; negative questions are ignored (see [CLOUD_VLM.md](CLOUD_VLM.md) for details).

## Running the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The server will start at `http://localhost:8000`

## API Endpoints

### Procedure Control

- **POST /start_procedure** - Start a new procedure for a user
  - Parameters: `username`, `procedure_file` (optional)
  - Returns: `{ok: true, procedure_id: "..."}`

- **GET /status** - Get user's current status
  - Parameters: `username`
  - Returns: State object with current step info

- **POST /pause** - Pause active procedure
  - Parameters: `username`
  - Returns: `{ok: true}`

- **POST /resume** - Resume paused procedure
  - Parameters: `username`
  - Returns: `{ok: true}`

- **POST /abort** - Abort active procedure
  - Parameters: `username`
  - Returns: `{ok: true}`

- **POST /trigger_stream_reconnect** - Trigger immediate RTSP stream reconnection
  - No parameters required
  - Returns: `{ok: true, message: "Stream reconnection triggered"}`

### Frame Ingestion

- **POST /ingest** - Upload a frame for analysis
  - Form data: `username`, `frame_id`, `file` (image)
  - Returns: `{ok: true, queued: true}`

### VLM Callback

- **POST /vlm/callback** - Receive VLM analysis results (called by VLM service)
  - Query params: `user`, `procedure_id`, `step_id`, `frame_id`, `idem`
  - Body: `{decision: "YES"|"NO"|"UNCERTAIN"|"NOT_APPLICABLE"}`
  - Returns: `{ok: true}`

## Usage Example

### 1. Start a procedure
```bash
curl -X POST "http://localhost:8000/start_procedure?username=john&procedure_file=app/data/procedures/pizza_custom.json"
```

### 2. Send frames
```bash
curl -X POST "http://localhost:8000/ingest" \
  -F "username=john" \
  -F "frame_id=frame_001" \
  -F "file=@image.jpg"
```

### 3. Check status
```bash
curl "http://localhost:8000/status?username=john"
```

## Procedure Format

Procedures are defined in JSON files in [`app/data/procedures/`](app/data/procedures/):

```json
{
  "id": "pizza_custom@v1",
  "name": "Make a Custom Pizza",
  "version": 1,
  "steps": [
    {
      "id": 1,
      "name": "Show pizza dough",
      "positives": ["A plain pizza base or dough is clearly visible..."],
      "negatives": ["No pizza base or dough is visible..."],
      "timeout_s": 20,
      "debounce": {
        "consecutive_yes": 2
      }
    }
  ]
}
```

## State Machine Logic

- **Frame buffering**: Up to 10 frames per user (configurable)
- **Single in-flight**: Only one VLM request active per user at a time
- **YES-only progression**: Only YES decisions increment the counter
- **Debounce**: Requires 2 consecutive YES responses by default
- **Timeout reset**: Timeout resets the YES counter but keeps the same step

## Project Structure

```
oneshot_copilot/
├── app/
│   ├── main.py                      # FastAPI application
│   ├── config.py                    # Configuration settings
│   ├── models/
│   │   ├── state.py                # UserState, Decision enums
│   │   └── procedure.py            # ProcedureDef, StepDef
│   ├── core/
│   │   ├── statemachine.py         # State machine logic
│   │   ├── vlm_client.py           # VLM HTTP client
│   │   ├── callbacks.py            # Event callbacks
│   │   └── frame_store.py          # Frame storage
│   ├── services/
│   │   ├── stream_quality_filter.py # RTSP stream ingestion
│   │   └── status_service.py       # Status tracking
│   └── api/
│       ├── procedure.py            # Procedure endpoints
│       ├── ingest.py               # Frame ingestion
│       └── vlm_callback.py         # VLM callback handler
└── app/data/
    └── procedures/
        └── pizza_custom.json       # Example procedure
```

## Development

The server includes auto-reload for development:
```bash
uvicorn app.main:app --reload
```

## License

MIT