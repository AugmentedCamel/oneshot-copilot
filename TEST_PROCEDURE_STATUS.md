# Procedure Status Service - Testing Documentation

This document provides instructions for testing the newly implemented procedure status service.

## Overview

The procedure status service consists of:
- **API Endpoint**: [`GET /api/procedure`](app/api/procedure.py:126) - Returns procedure status for a user
- **Status Service**: [`app/services/status_service.py`](app/services/status_service.py:1) - Manages JSON file persistence
- **State Machine Method**: [`get_procedure_status()`](app/core/statemachine.py:228) - Generates status JSON
- **Auto-save Integration**: Status files saved to [`app/data/user_status/`](app/data/user_status/) on state changes

## Test Script

A comprehensive test script has been created: [`test_procedure_status.sh`](test_procedure_status.sh)

### Running the Tests

1. **Start the server** (in a separate terminal):
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. **Run the test script**:
   ```bash
   # On Linux/Mac:
   bash test_procedure_status.sh
   
   # On Windows with Git Bash:
   bash test_procedure_status.sh
   
   # With custom test image:
   bash test_procedure_status.sh path/to/your/image.jpg
   ```

## Test Coverage

The test script verifies the following:

### ✅ Test 1: Error Case - Non-existent User
- Requests status for a user that doesn't exist
- Verifies 404 response is returned
- **Expected**: HTTP 404 with error message

### ✅ Test 2: Initial Status After Starting Procedure
- Starts a new procedure for a test user
- Calls `GET /api/procedure?username=<username>`
- Verifies JSON response structure:
  - `username`: Correct username
  - `id`: "pizza_custom@v1"
  - `name`: "Make a Custom Pizza"
  - `version`: 1
  - `steps`: Array with correct structure
- Verifies initial step statuses:
  - Step 1: "in_progress"
  - Step 2: "todo"
  - Step 3: "todo"

### ✅ Test 3: File Persistence
- Verifies JSON file created in `app/data/user_status/`
- Checks filename format: `{username}_{procedure_id}.json`
- Verifies file contents match API response
- Confirms proper JSON structure

### ✅ Test 4: Status Transitions
- Progresses through step 1 (2 consecutive YES responses)
- Verifies status updates correctly:
  - Step 1: "done"
  - Step 2: "in_progress"
  - Step 3: "todo"
- Confirms both API and file reflect changes

### ✅ Test 5: Complete All Steps
- Completes all 3 steps of the procedure
- Verifies final status:
  - Step 1: "done"
  - Step 2: "done"
  - Step 3: "done"
- Confirms file persistence after completion

### ✅ Test 6: Abort Scenario
- Starts a procedure and immediately aborts it
- Verifies status file still exists
- Checks status reflects aborted state

### ✅ Test 7: Multiple Users - Isolation
- Starts procedures for multiple users simultaneously
- Progresses one user while leaving another at initial state
- Verifies each user has separate status file
- Confirms statuses are properly isolated

### ✅ Test 8: Filename Sanitization
- Tests with potentially dangerous username (path traversal attempt)
- Verifies server doesn't crash
- Confirms no files created outside status directory
- Validates security of file path handling

## Manual Testing

If you prefer manual testing, use these curl commands:

### 1. Test Non-existent User (Should return 404)
```bash
curl "http://localhost:8000/api/procedure?username=nonexistent_user"
```

### 2. Start Procedure and Check Initial Status
```bash
# Start procedure
curl -X POST "http://localhost:8000/start_procedure?username=testuser&procedure_file=app/data/procedures/pizza_custom.json"

# Check status via new endpoint
curl "http://localhost:8000/api/procedure?username=testuser"

# Expected response:
{
  "username": "testuser",
  "id": "pizza_custom@v1",
  "name": "Make a Custom Pizza",
  "version": 1,
  "steps": [
    {"id": 1, "name": "Show pizza dough", "status": "in_progress"},
    {"id": 2, "name": "Add mushrooms", "status": "todo"},
    {"id": 3, "name": "Add chilli peppers", "status": "todo"}
  ]
}
```

### 3. Verify File Persistence
```bash
# Check if file was created
ls -la app/data/user_status/testuser_pizza_custom@v1.json

# View file contents (on Windows, use 'type' instead of 'cat')
cat app/data/user_status/testuser_pizza_custom@v1.json
```

### 4. Progress Through Steps
```bash
# Upload frame and simulate 2 YES responses for step 1
curl -X POST http://localhost:8000/ingest \
  -F "username=testuser" \
  -F "frame_id=f1" \
  -F "file=@test_image.jpg"

curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=1&frame_id=f1&idem=f1" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

curl -X POST http://localhost:8000/ingest \
  -F "username=testuser" \
  -F "frame_id=f2" \
  -F "file=@test_image.jpg"

curl -X POST "http://localhost:8000/vlm/callback?user=testuser&procedure_id=pizza_custom@v1&step_id=1&frame_id=f2&idem=f2" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}'

# Check updated status
curl "http://localhost:8000/api/procedure?username=testuser"

# Expected: Step 1 = "done", Step 2 = "in_progress", Step 3 = "todo"
```

## Implementation Details

### API Endpoint
Location: [`app/api/procedure.py`](app/api/procedure.py:125-147)

```python
@router.get("/procedure")
async def get_procedure_status(username: str) -> Dict:
    """Get current procedure status with steps for a user."""
    status_data = machine.get_procedure_status(username)
    
    if not status_data:
        raise HTTPException(status_code=404, 
                          detail=f"No active procedure for user: {username}")
    
    return status_data
```

### Status Service
Location: [`app/services/status_service.py`](app/services/status_service.py)

Key functions:
- `save_user_status()`: Saves status to JSON file (thread-safe)
- `load_user_status()`: Loads status from JSON file
- `get_status_file_path()`: Generates safe file path with sanitization

### State Machine Integration
Location: [`app/core/statemachine.py`](app/core/statemachine.py:228-267)

The `get_procedure_status()` method:
- Returns None if no active procedure
- Generates step statuses based on current state:
  - "done": Steps before current_index or if procedure completed
  - "in_progress": Current step (when state is WORKING)
  - "todo": Steps after current_index

Auto-save integration:
- Called after starting procedure (line 183)
- Called after step progression (line 328)
- Called after completion (line 336)
- Called after abort (line 212)

## Expected Behavior

### JSON Response Format
```json
{
  "username": "user123",
  "id": "pizza_custom@v1",
  "name": "Make a Custom Pizza",
  "version": 1,
  "steps": [
    {
      "id": 1,
      "name": "Show pizza dough",
      "status": "done"
    },
    {
      "id": 2,
      "name": "Add mushrooms",
      "status": "in_progress"
    },
    {
      "id": 3,
      "name": "Add chilli peppers",
      "status": "todo"
    }
  ]
}
```

### File Location
Files are saved to: `app/data/user_status/{username}_{procedure_id}.json`

Example: `app/data/user_status/testuser_pizza_custom@v1.json`

### Status Transitions
- **Initial**: Step 1 = "in_progress", others = "todo"
- **After Step 1**: Step 1 = "done", Step 2 = "in_progress", Step 3 = "todo"
- **After Step 2**: Steps 1-2 = "done", Step 3 = "in_progress"
- **Completed**: All steps = "done"
- **Aborted**: Status reflects state at time of abort

## Troubleshooting

### Server Not Running
If you get connection errors:
```bash
# Start the server first
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Missing Test Image
If test image is missing:
```bash
# Create placeholder (requires ImageMagick)
convert -size 640x480 xc:white test_image.jpg

# Or download sample
curl -o test_image.jpg https://via.placeholder.com/640x480

# Or use any existing image
cp /path/to/your/image.jpg test_image.jpg
```

### Permission Issues on Windows
Windows doesn't support chmod. Run the script directly:
```bash
bash test_procedure_status.sh
```

### File Not Found Errors
Ensure you're in the project root directory:
```bash
cd C:/Users/mikam/Local/oneshot/oneshot-copilot
```

## Success Criteria

All tests pass when:
1. ✅ 404 returned for non-existent users
2. ✅ Initial status shows correct step states
3. ✅ Files are created in correct location with correct format
4. ✅ Status transitions work correctly through all steps
5. ✅ Completion state shows all steps as "done"
6. ✅ Abort scenario handled properly
7. ✅ Multiple users have isolated statuses
8. ✅ Filename sanitization prevents path traversal

## Integration with Existing Tests

This new endpoint complements the existing [`test_workflow.sh`](test_workflow.sh) script. You can:
1. Run `test_workflow.sh` for end-to-end workflow testing
2. Run `test_procedure_status.sh` for specific status endpoint testing
3. Both can be run sequentially for comprehensive coverage

## Next Steps

After successful testing:
1. Review the test output for any failures
2. Check the created status files in `app/data/user_status/`
3. Verify logs show proper status save operations
4. Consider adding these tests to CI/CD pipeline