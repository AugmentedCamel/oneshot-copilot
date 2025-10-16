# RTSP/RTMP Stream Integration

## Overview

Oneshot Copilot now supports automatic frame ingestion from RTSP/RTMP streams. When configured, the application will:

1. Connect to your camera/stream on startup
2. Continuously read frames from the stream
3. Filter frames by quality (blur and brightness thresholds)
4. Automatically POST high-quality frames to the `/api/ingest` endpoint
5. Process frames at approximately 1 frame per second

## Automatic Reconnection

The stream ingestion service now includes **automatic retry logic**:

- ✅ **Checks every 10 seconds** if the stream is unavailable
- ✅ **Automatic reconnection** when stream becomes available
- ✅ **Graceful error handling** - won't crash if stream is offline
- ✅ **Manual trigger** available via API endpoint
- ✅ **Continuous monitoring** throughout application lifetime

This means you can:
1. Start the application before your camera is ready
2. Turn your camera/stream on and off as needed
3. The service will automatically detect and reconnect

## Configuration

### 1. Update your `.env` file:

```env
# Your existing configuration...
SELF_URL=http://localhost:8000
MENTRA_URL=https://client-webhook.example.com
VLM_URL=http://localhost:8080

# Add these for stream ingestion:
RTSP_STREAM_URL=rtsp://192.168.1.100:8554/live/stream
STREAM_USERNAME=camera_user
```

### 2. Configuration Options

- **`RTSP_STREAM_URL`**: Your RTSP or RTMP stream URL
  - Leave empty (`RTSP_STREAM_URL=`) to disable stream ingestion
  - Examples:
    - `rtsp://192.168.1.100:8554/live/stream`
    - `rtmp://server.example.com/live/mystream`

- **`STREAM_USERNAME`**: Username identifier for stream frames
  - Default: `stream_user`
  - Used to identify which user the stream frames belong to

## How It Works

### Automatic Connection & Retry

The stream service runs continuously in the background:

```
Application Starts
       ↓
Check for RTSP_STREAM_URL
       ↓
   Is stream available?
   ├─ Yes → Connect & process frames
   │         ↓
   │    Stream disconnects
   │         ↓
   └─ No  → Wait 10 seconds → Retry
```

**Key Features:**
- Starts checking immediately on application startup
- Retries every 10 seconds if connection fails
- Automatically reconnects if stream disconnects
- Logs all connection attempts and failures
- Can be manually triggered via API endpoint

### Quality Filtering

The stream quality filter automatically:
- ✅ Analyzes blur (Laplacian variance > 100)
- ✅ Checks brightness (50-250 range on 0-255 scale)
- ✅ Maintains frame rate limiting (1 frame/second by default)
- ✅ Uses low-latency mode for real-time processing

### Integration Flow

```
RTSP Stream → Quality Filter → /api/ingest → State Machine → VLM Service
                    ↓
              (Filters out blurry/dark/bright frames)
```

### Background Task

The stream ingestion runs as a background task that:
- Starts automatically when the application launches
- Runs independently without blocking other operations
- Gracefully handles stream disconnections
- Can be stopped/restarted with application lifecycle

## Usage

### Starting with Stream Ingestion

1. Configure your `.env` file with stream URL
2. Start the application:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
3. The stream will start automatically and you'll see logs like:
   ```
   Starting stream quality filter for: rtsp://...
   Stream frames will be posted to: http://localhost:8000/api/ingest
   Stream username: camera_user
   ```

### Starting a Procedure for Stream User

Before the stream can be processed, start a procedure for the stream user:

```bash
curl -X POST "http://localhost:8000/api/start_procedure?username=camera_user&procedure_file=app/data/procedures/pizza_custom.json"
```

Now frames from the stream will be automatically analyzed against the procedure steps!

### Monitoring Stream Status

Check the status of the stream user:

```bash
curl "http://localhost:8000/api/status?username=camera_user"
```

### Manually Triggering Reconnection

If you know a stream has just become available (e.g., after starting a camera), you can trigger an immediate reconnection attempt:

```bash
curl -X POST "http://localhost:8000/api/trigger_stream_reconnect"
```

This is useful when:
- You just turned on your camera
- You know the stream URL changed
- You want to force a reconnection without waiting for the next retry interval

### Disabling Stream Ingestion

To disable stream ingestion, either:
1. Leave `RTSP_STREAM_URL` empty in `.env`
2. Remove the `RTSP_STREAM_URL` line from `.env`
3. Restart the application

## Technical Details

### Dependencies

All required dependencies are already in `requirements.txt`:
- `opencv-python` - Video capture and frame processing
- `numpy` - Image array operations
- `requests` - HTTP POST to /ingest endpoint

### Stream Quality Filter

The filter uses the `StreamQualityFilter` class from `app/services/stream_quality_filter.py`:
- Reads frames via OpenCV VideoCapture
- Calculates blur score using Laplacian variance
- Measures brightness as grayscale mean
- Posts frames asynchronously in separate thread
- Handles reconnection and error recovery

### Performance

- **Frame Rate**: ~1 frame/second to avoid overload
- **Quality Checks**: ~5ms per frame
- **POST Requests**: Non-blocking, runs in separate thread
- **Memory**: Minimal buffering (30 frames max)
- **CPU**: Low impact with aggressive buffer flushing

## Troubleshooting

### Stream Not Connecting

The service will automatically retry every 10 seconds. Check logs to see retry attempts:

```
Stream connection failed: [Errno 111] Connection refused
Will retry connection in 10s
```

**Troubleshooting steps:**
1. Verify the RTSP URL is correct and accessible
2. Check firewall/network settings
3. Ensure the camera/server is actually streaming
4. Test the stream URL with VLC or ffplay:
   ```bash
   ffplay rtsp://your-stream-url
   ```
5. Trigger manual reconnection:
   ```bash
   curl -X POST "http://localhost:8000/api/trigger_stream_reconnect"
   ```

### No Frames Being Sent

1. Check that frames meet quality thresholds:
   - Blur score > 100
   - Brightness between 50-250
2. Verify the stream user has an active procedure
3. Check application logs for quality rejection reasons

### Stream Keeps Disconnecting

The service will automatically reconnect each time. Check logs for patterns:
- Network instability
- Camera reboots
- Firewall timeouts

The application will continue running and automatically reconnect when the stream is available.

## Example Setup

Complete example for a home security camera:

```env
# .env
SELF_URL=http://localhost:8000
MENTRA_URL=https://your-webhook.com
VLM_URL=http://localhost:8080
RTSP_STREAM_URL=rtsp://192.168.1.50:554/stream1
STREAM_USERNAME=front_door_camera
```

Start procedure:
```bash
curl -X POST "http://localhost:8000/api/start_procedure?username=front_door_camera&procedure_file=app/data/procedures/pizza_custom.json"
```

The camera will now automatically feed frames into your procedure!