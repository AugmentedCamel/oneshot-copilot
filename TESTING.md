# Testing Guide for Oneshot Copilot

This guide provides CLI commands to manually test the application.

## Prerequisites

1. **Start the server**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. **Create a test .env file** (if not already done)
```bash
cp .env.example .env
```

3. **Create a test image** (or use any image file)
```bash
# Use any image file, e.g., test_image.jpg
# For testing, any JPEG/PNG file will work
```

## Complete Test Workflow

### 1. Check Server Health

```bash
# Check if server is running
curl http://localhost:8000/health

# Expected: {"status":"healthy"}
```

### 2. Start a Procedure

```bash
# Start the pizza procedure for user "testuser"
curl -X POST "http://localhost:8000/start_procedure?username=testuser&procedure_file=app/data/procedures/pizza_custom.json"

# Expected: {"ok":true,"procedure_id":"pizza_custom@v1"}
```

### 3. Check User Status

```bash
# Get current status
curl "http://localhost:8000/status?username=testuser"

# Expected output:
# {
#   "username": "testuser",
#   "state": "WORKING",
#   "procedure_id": "pizza_custom@v1",
#   "current_step_id": 1,
#   "current_step_name": "Show pizza dough",
#   "yes_consecutive": 0,
#   "inflight": false,
#   "buffer_len": 0
# }
```

### 4. Ingest Frames (Upload Images)

```bash
# Upload first frame
curl -X POST http://localhost:8000/ingest \
  -F "username=testuser" \
  -F "frame_id=frame_001" \
  -F "file=@test_image.jpg"

# Expected: {"ok":true,"queued":true,"frame_id":"frame_001","username":"testuser"}

# Upload second frame
curl -X POST http://localhost:8000/ingest \
  -F "username=testuser" \
  -F "frame_id=frame_002" \
  -F "file=@test_image.jpg"

# Upload third frame
curl -X POST http://localhost:8000/ingest \
  -F "username=testuser" \
  -F "frame_id=frame_003" \
  -F "file=@test_image.jpg"
```

### 5. Simulate VLM Callback (Manual Testing)

Since you may not have a real VLM service running, you can manually simulate the VLM response:

```bash
# Simulate VLM responding with "YES" for frame_001
curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=1&frame_id=frame_001&idem=frame_001" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# Expected: {"ok":true,"username":"testuser","frame_id":"frame_001","decision":"YES"}

# Check status after first YES
curl "http://localhost:8000/status?username=testuser"
# Should show "yes_consecutive": 1

# Simulate second YES (this should trigger progression to next step)
curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=1&frame_id=frame_002&idem=frame_002" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# Check status - should now be on step 2
curl "http://localhost:8000/status?username=testuser"
# Should show "current_step_id": 2, "current_step_name": "Add mushrooms"
```

### 6. Test Other Decisions

```bash
# Simulate NO response (resets counter)
curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_003&idem=frame_003" \
  -H "Content-Type: application/json" \
  -d '{"decision": "NO"}'

# Simulate UNCERTAIN response
curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_004&idem=frame_004" \
  -H "Content-Type: application/json" \
  -d '{"decision": "UNCERTAIN"}'

# Simulate NOT_APPLICABLE response
curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_005&idem=frame_005" \
  -H "Content-Type: application/json" \
  -d '{"decision": "NOT_APPLICABLE"}'
```

### 7. Pause and Resume

```bash
# Pause the procedure
curl -X POST "http://localhost:8000/pause?username=testuser"
# Expected: {"ok":true}

# Check status (should show "PAUSED")
curl "http://localhost:8000/status?username=testuser"

# Try to ingest a frame while paused (will be buffered but not dispatched)
curl -X POST http://localhost:8000/ingest \
  -F "username=testuser" \
  -F "frame_id=frame_pause" \
  -F "file=@test_image.jpg"

# Resume the procedure
curl -X POST "http://localhost:8000/resume?username=testuser"
# Expected: {"ok":true}

# Check status (should show "WORKING" again)
curl "http://localhost:8000/status?username=testuser"
```

### 8. Abort Procedure

```bash
# Abort the current procedure
curl -X POST "http://localhost:8000/abort?username=testuser"
# Expected: {"ok":true}

# Check status (should show "ABORTED")
curl "http://localhost:8000/status?username=testuser"
```

## Complete Test Sequence (Copy-Paste Ready)

```bash
# 1. Start procedure
curl -X POST "http://localhost:8000/start_procedure?username=alice&procedure_file=app/data/procedures/pizza_custom.json"

# 2. Check status
curl "http://localhost:8000/status?username=alice"

# 3. Upload frame
curl -X POST http://localhost:8000/ingest \
  -F "username=alice" \
  -F "frame_id=f1" \
  -F "file=@test_image.jpg"

# 4. Simulate first YES
curl -X POST "http://localhost:8000/vlm/callback?user=alice&procedure_id=pizza_custom@v1&step_id=1&frame_id=f1&idem=f1" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# 5. Upload another frame
curl -X POST http://localhost:8000/ingest \
  -F "username=alice" \
  -F "frame_id=f2" \
  -F "file=@test_image.jpg"

# 6. Simulate second YES (triggers step progression)
curl -X POST "http://localhost:8000/vlm/callback?user=alice&procedure_id=pizza_custom@v1&step_id=1&frame_id=f2&idem=f2" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# 7. Check status (should be on step 2 now)
curl "http://localhost:8000/status?username=alice"

# 8. Continue with step 2 (same pattern - 2 YES needed)
curl -X POST http://localhost:8000/ingest \
  -F "username=alice" \
  -F "frame_id=f3" \
  -F "file=@test_image.jpg"

curl -X POST "http://localhost:8000/vlm/callback?user=alice&procedure_id=pizza_custom@v1&step_id=2&frame_id=f3&idem=f3" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

curl -X POST http://localhost:8000/ingest \
  -F "username=alice" \
  -F "frame_id=f4" \
  -F "file=@test_image.jpg"

curl -X POST "http://localhost:8000/vlm/callback?user=alice&procedure_id=pizza_custom@v1&step_id=2&frame_id=f4&idem=f4" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# 9. Check status (should be on step 3)
curl "http://localhost:8000/status?username=alice"

# 10. Complete step 3
curl -X POST http://localhost:8000/ingest \
  -F "username=alice" \
  -F "frame_id=f5" \
  -F "file=@test_image.jpg"

curl -X POST "http://localhost:8000/vlm/callback?user=alice&procedure_id=pizza_custom@v1&step_id=3&frame_id=f5&idem=f5" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

curl -X POST http://localhost:8000/ingest \
  -F "username=alice" \
  -F "frame_id=f6" \
  -F "file=@test_image.jpg"

curl -X POST "http://localhost:8000/vlm/callback?user=alice&procedure_id=pizza_custom@v1&step_id=3&frame_id=f6&idem=f6" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# 11. Check final status (should be COMPLETED)
curl "http://localhost:8000/status?username=alice"
```

## Testing Multiple Users

```bash
# Start procedures for multiple users
curl -X POST "http://localhost:8000/start_procedure?username=user1&procedure_file=app/data/procedures/pizza_custom.json"
curl -X POST "http://localhost:8000/start_procedure?username=user2&procedure_file=app/data/procedures/pizza_custom.json"

# Check both statuses
curl "http://localhost:8000/status?username=user1"
curl "http://localhost:8000/status?username=user2"

# Upload frames for both users
curl -X POST http://localhost:8000/ingest -F "username=user1" -F "frame_id=u1_f1" -F "file=@test_image.jpg"
curl -X POST http://localhost:8000/ingest -F "username=user2" -F "frame_id=u2_f1" -F "file=@test_image.jpg"
```

## Creating a Test Image

If you don't have a test image, create one:

### Option 1: Using ImageMagick
```bash
convert -size 640x480 xc:white test_image.jpg
```

### Option 2: Download a sample
```bash
curl -o test_image.jpg https://via.placeholder.com/640x480
```

### Option 3: Use any existing image
```bash
# Just copy any JPEG/PNG file you have
cp /path/to/your/image.jpg test_image.jpg
```

## Expected Behavior

- **Frame ingestion**: Frames are buffered (max 10 per user)
- **VLM dispatch**: Only when not inflight and user is WORKING
- **Debounce**: Need 2 consecutive YES to progress
- **NO/UNCERTAIN/NOT_APPLICABLE**: Resets the YES counter
- **Step progression**: Automatic when debounce satisfied
- **Completion**: State becomes COMPLETED after last step

## Troubleshooting

### Server not responding
```bash
# Check if server is running
ps aux | grep uvicorn

# Check logs
# (logs appear in the terminal where uvicorn is running)
```

### Port already in use
```bash
# Use a different port
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### File upload errors
```bash
# Make sure file exists
ls -la test_image.jpg

# Check file permissions
chmod 644 test_image.jpg
```

## API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

These provide interactive API documentation and testing interfaces.