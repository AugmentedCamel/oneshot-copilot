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

## Requirements

### Core Requirements
- **Python 3.8+** with pip
- **FastAPI** and dependencies (see `requirements.txt`)
- **VLM Service** (Vision Language Model) - Choose one option:
  - **Local Auki VLM Node** (Recommended for development):
    - Repository: [Auki Labs VLM Node](https://github.com/aukilabs/vlm-node/tree/main)
    - Requires Docker with GPU support
    - Must run on port **8080**
  - **Cloud VLM**: [Moondream AI](https://moondream.ai) account with API key

### Mentra Integration (Required)
- **Mentra Account** with:
  - API key
  - App domain (`app.com.domain`)
- Setup tutorial: [MentraOS Extended Example](https://github.com/Mentra-Community/MentraOS-Extended-Example-App/blob/main/README.md)

### RTSP/RTMP Streaming (Optional)
For automatic frame ingestion from video streams:
- **RTSP/RTMP Server** (local or remote)
- For local testing, you can use MediaMTX:
  ```bash
  docker pull bluenviron/mediamtx
  docker run --rm -it -p 8554:8554 -p 1935:1935 bluenviron/mediamtx
  ```
- Configure `RTSP_STREAM_URL` in `.env` to enable

## Installation

1. **Clone the repository**
```bash
cd oneshot_copilot
```

2. **Create a virtual python environment in the root folder and run it.**
```bash
venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment**
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

### Local VLM Setup (Auki VLM Node)

For local development, you can use the Auki Labs VLM Node which provides vision language model capabilities:

#### Prerequisites
- Docker with GPU support (NVIDIA GPU recommended)
- NVIDIA Container Toolkit installed
- At least 8GB GPU VRAM

#### Setup Instructions

1. **Clone the Auki VLM Node repository**:
   ```bash
   git clone https://github.com/aukilabs/vlm-node.git
   cd vlm-node
   ```

2. **Build and run with GPU support**:
   ```bash
   make docker-gpu
   ```

3. **Verify the service is running**:
   The VLM Node will start on **port 8080** by default. You can verify it's running:
   ```bash
   curl http://localhost:8080/health
   ```

4. **Configure Oneshot Copilot to use the local VLM**:
   In your `.env` file, set:
   ```env
   VLM_URL=http://localhost:8080
   USE_CLOUD_VLM=false
   ```

**Note**: The Auki VLM Node must be running before starting the Oneshot Copilot server.

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

**Important Note**: Moondream AI cloud does not support negative questions. When using cloud VLM, only positive questions from procedures are sent; negative questions are ignored (see [CLOUD_VLM.md](CLOUD_VLM.md) for details). Moondream AI cloud is also **rate limited**.

## Mentra App Structure and Configuration

The Mentra app is a separate application that provides the frontend interface and handles user authentication for Oneshot Copilot. It's built using Express.js and the Mentra SDK.

### Directory Structure

```
MentraApp/
├── src/
│   ├── index.ts                    # Main application entry point
│   ├── tools.ts                    # Mentra SDK tools integration
│   ├── webview.ts                  # Web view management
│   └── services/
│       ├── AudioFeedback.ts        # Audio feedback service
│       └── UserMetadataService.ts  # User metadata handling
├── views/
│   ├── login_view.ejs              # Login page template
│   ├── mainwebview.ejs             # Main interface template
│   └── taskview.ejs                # Task view template
├── public/
│   └── css/
│       └── style.css               # Application styles
├── .env                            # Environment configuration (create from .env.example)
├── .env.example                    # Example environment configuration
├── package.json                    # Node.js dependencies
└── tsconfig.json                   # TypeScript configuration
```

### Mentra App Environment Configuration

Create a `.env` file in the `MentraApp` directory based on `.env.example`:

```env
# Mentra OS API Key (required)
# Get this from your Mentra developer account at https://mentra.com
MENTRAOS_API_KEY=your_mentra_api_key_here

# Port for the Mentra app (default: 3000)
PORT=3000

# Package name for your Mentra application
# This should match your app registration in Mentra OS
PACKAGE_NAME=com.yourcompany.oneshotcopilot

# RTMP stream URL (optional)
# URL to the RTMP server for streaming video frames
# Must match the RTSP_STREAM_URL configuration in the main app
RTMP_URL=rtmp://192.168.1.100:1935/live/oneshot
```

### Configuration Parameters Explained

- **`MENTRAOS_API_KEY`** (Required): Your Mentra OS API key obtained from the Mentra developer portal
- **`PORT`** (Optional): The port on which the Mentra app will run (default: 3000)
- **`PACKAGE_NAME`** (Required): Your application's package identifier in Mentra OS (e.g., `com.yourcompany.oneshotcopilot`)
- **`RTMP_URL`** (Optional): The RTMP stream URL for video ingestion, should correspond to the RTSP stream configured in the main application

### Dependencies

The Mentra app requires:
- **Node.js** 18 or higher (up to Node.js 22)
- **Bun** runtime (recommended) or npm
- **Mentra SDK** (`@mentra/sdk`)
- **Express.js** for the web server
- **EJS** for templating


## Running the Application

### 0. Start the VLM Node (Required for Local VLM)

If using the local Auki VLM Node (recommended for development):

1. **Navigate to the VLM Node directory**:
   ```bash
   cd vlm-node
   ```

2. **Start the VLM service with GPU support**:
   ```bash
   make docker-gpu
   ```

3. **Verify it's running** on port 8080:
   ```bash
   curl http://localhost:8080/health
   ```

**Note**: If using Moondream AI cloud VLM instead, skip this step and ensure `USE_CLOUD_VLM=true` in your `.env` file.

### 1. Start the Mentra App (Required)

The Mentra app handles user authentication and provides the frontend interface. It must be started before the main server.

1. **Setup Mentra** following the [MentraOS Extended Example tutorial](https://github.com/Mentra-Community/MentraOS-Extended-Example-App/blob/main/README.md)

2. **Configure environment** - Get API keys and configure `.env` in the `MentraApp` directory:
   ```bash
   cd MentraApp
   cp .env.example .env
   # Edit .env with your Mentra credentials
   ```

3. **Install dependencies and start**:
   ```bash
   bun update
   bun run dev
   ```

4. **Expose with Ngrok** - Follow the tutorial to expose your local port with Ngrok

### 2. Start the Oneshot Copilot Server

After Mentra is running, start the main FastAPI server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The server will start at `http://localhost:8000`
Make sure to expose the server with Ngrok 

**Note**: For development with auto-reload, you can use:
```bash
uvicorn app.main:app --reload
```

## Running the RTMP Server (required)
``docker pull bluenviron/mediamtx``

``docker run --rm -p 1935:1935 -p 8554:8554 -p 8888:8888 bluenviron/mediamtx``
Link to the Repo: https://github.com/bluenviron/mediamtx

## SERVER API Endpoints

### Procedure Control (*not thoroughly tested)

- **POST /start_procedure** - Start a new procedure for a user
  - Parameters: `username`, `procedure_file` (optional)
  - Returns: `{ok: true, procedure_id: "..."}`

- **GET /status** - Get user's current status
  - Parameters: `username`
  - Returns: State object with current step info

- ***POST /pause** - Pause active procedure
  - Parameters: `username`
  - Returns: `{ok: true}`

- ***POST /resume** - Resume paused procedure
  - Parameters: `username`
  - Returns: `{ok: true}`

- ***POST /abort** - Abort active procedure
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
Disclaimer: Multi-user has not been tested yet, so far usernames have been hardcoded.

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

## Authors

- Mika Haak "@augmentedcamel"

## License

MIT
