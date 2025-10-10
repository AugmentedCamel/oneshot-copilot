pip # Quick Start Guide

## 1. Setup (One-time)

```bash
# Install dependencies
pip install -r requirements.txt

# Create and configure .env
cp .env.example .env
# Edit .env if needed (defaults work for local testing)
```

## 2. Start Server

```bash
# Terminal 1: Start the server
uvicorn app.main:app --reload
```

## 3. Test with CLI Commands

### Quick Test (Copy-Paste All at Once)

```bash
# Start procedure
curl -X POST "http://localhost:8000/start_procedure?username=demo&procedure_file=app/data/procedures/pizza_custom.json"

# Upload frame 1
curl -X POST http://localhost:8000/ingest -F "username=demo" -F "frame_id=f1" -F "file=@test_image.jpg"

# Simulate YES #1
curl -X POST "http://localhost:8000/vlm/callback?user=demo&procedure_id=pizza_custom@v1&step_id=1&frame_id=f1&idem=f1" -H "Content-Type: application/json" -d '{"decision":"YES"}'

# Upload frame 2
curl -X POST http://localhost:8000/ingest -F "username=demo" -F "frame_id=f2" -F "file=@test_image.jpg"

# Simulate YES #2 (advances to step 2)
curl -X POST "http://localhost:8000/vlm/callback?user=demo&procedure_id=pizza_custom@v1&step_id=1&frame_id=f2&idem=f2" -H "Content-Type: application/json" -d '{"decision":"YES"}'

# Check status
curl "http://localhost:8000/status?username=demo"
```

### Create Test Image (if needed)

```bash
# Option 1: Placeholder image
curl -o test_image.jpg https://via.placeholder.com/640x480

# Option 2: With ImageMagick
convert -size 640x480 xc:white test_image.jpg

# Option 3: Use any existing image
cp your_image.jpg test_image.jpg
```

## 4. Automated Test

```bash
# Make script executable
chmod +x test_workflow.sh

# Run complete test workflow
./test_workflow.sh test_image.jpg
```

## Essential Commands Reference

### Start Procedure
```bash
curl -X POST "http://localhost:8000/start_procedure?username=USER&procedure_file=app/data/procedures/pizza_custom.json"
```

### Check Status
```bash
curl "http://localhost:8000/status?username=USER"
```

### Upload Frame
```bash
curl -X POST http://localhost:8000/ingest \
  -F "username=USER" \
  -F "frame_id=FRAME_ID" \
  -F "file=@image.jpg"
```

### Simulate VLM Response
```bash
curl -X POST "http://localhost:8000/vlm/callback?user=USER&procedure_id=pizza_custom@v1&step_id=STEP&frame_id=FRAME&idem=FRAME" \
  -H "Content-Type: application/json" \
  -d '{"decision":"YES"}'
```

### Pause/Resume/Abort
```bash
curl -X POST "http://localhost:8000/pause?username=USER"
curl -X POST "http://localhost:8000/resume?username=USER"
curl -X POST "http://localhost:8000/abort?username=USER"
```

## API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Full Documentation

- **Complete Testing Guide**: See [`TESTING.md`](TESTING.md)
- **Project Documentation**: See [`README.md`](README.md)