#!/bin/bash

# Oneshot Copilot - Automated Test Workflow
# This script demonstrates a complete test cycle

set -e  # Exit on error

BASE_URL="http://localhost:8000"
USERNAME="testuser"
IMAGE_FILE="${1:-test_image.jpg}"

echo "=========================================="
echo "Oneshot Copilot - Test Workflow"
echo "=========================================="
echo ""

# Check if image file exists
if [ ! -f "$IMAGE_FILE" ]; then
    echo "❌ Error: Image file '$IMAGE_FILE' not found"
    echo "Usage: ./test_workflow.sh [path/to/image.jpg]"
    echo ""
    echo "Creating a placeholder test image..."
    # Create a simple test image if ImageMagick is available
    if command -v convert &> /dev/null; then
        convert -size 640x480 xc:white -pointsize 30 -draw "text 200,240 'Test Image'" test_image.jpg
        echo "✅ Created test_image.jpg"
        IMAGE_FILE="test_image.jpg"
    else
        echo "Please provide a test image file or install ImageMagick"
        exit 1
    fi
fi

echo "Using image: $IMAGE_FILE"
echo "Testing user: $USERNAME"
echo ""

# Function to print step headers
step() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 STEP $1: $2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Function to check status
check_status() {
    echo "Current status:"
    curl -s "$BASE_URL/status?username=$USERNAME" | python3 -m json.tool || echo "Failed to get status"
    echo ""
}

# Wait for user to press enter
wait_for_user() {
    echo ""
    read -p "Press ENTER to continue..."
    echo ""
}

step 1 "Health Check"
echo "Checking if server is running..."
curl -s "$BASE_URL/health" | python3 -m json.tool
wait_for_user

step 2 "Start Procedure"
echo "Starting pizza_custom procedure for user '$USERNAME'..."
curl -s -X POST "$BASE_URL/start_procedure?username=$USERNAME&procedure_file=app/data/procedures/pizza_custom.json" | python3 -m json.tool
echo ""
check_status
wait_for_user

step 3 "Upload First Frame"
echo "Uploading frame_001..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_001" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
check_status
echo "Note: Frame is buffered and dispatched to VLM (in production)"
wait_for_user

step 4 "Simulate First YES Response"
echo "Simulating VLM callback with YES decision..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=1&frame_id=frame_001&idem=frame_001" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' | python3 -m json.tool
echo ""
check_status
echo "Note: yes_consecutive should be 1 (need 2 for progression)"
wait_for_user

step 5 "Upload Second Frame"
echo "Uploading frame_002..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_002" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
check_status
wait_for_user

step 6 "Simulate Second YES Response (Triggers Progression)"
echo "Simulating second YES - this should advance to step 2..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=1&frame_id=frame_002&idem=frame_002" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' | python3 -m json.tool
echo ""
check_status
echo "✅ Step 1 completed! Now on Step 2: 'Add mushrooms'"
wait_for_user

step 7 "Test Pause/Resume"
echo "Pausing procedure..."
curl -s -X POST "$BASE_URL/pause?username=$USERNAME" | python3 -m json.tool
echo ""
check_status
echo "State should be PAUSED"
echo ""
echo "Resuming procedure..."
curl -s -X POST "$BASE_URL/resume?username=$USERNAME" | python3 -m json.tool
echo ""
check_status
echo "State should be WORKING again"
wait_for_user

step 8 "Test NO Response (Resets Counter)"
echo "Uploading frame_003..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_003" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
echo "Simulating NO response (this resets the counter)..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_003&idem=frame_003" \
  -H "Content-Type: application/json" \
  -d '{"decision": "NO"}' | python3 -m json.tool
echo ""
check_status
echo "Note: yes_consecutive reset to 0"
wait_for_user

step 9 "Complete Step 2"
echo "Uploading frame_004..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_004" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
echo "First YES for step 2..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_004&idem=frame_004" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' | python3 -m json.tool
echo ""
check_status
echo ""
echo "Uploading frame_005..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_005" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
echo "Second YES for step 2..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_005&idem=frame_005" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' | python3 -m json.tool
echo ""
check_status
echo "✅ Step 2 completed! Now on Step 3: 'Add chilli peppers'"
wait_for_user

step 10 "Complete Step 3 (Final Step)"
echo "Uploading frame_006..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_006" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
echo "First YES for step 3..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=3&frame_id=frame_006&idem=frame_006" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' | python3 -m json.tool
echo ""
check_status
echo ""
echo "Uploading frame_007..."
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$USERNAME" \
  -F "frame_id=frame_007" \
  -F "file=@$IMAGE_FILE" | python3 -m json.tool
echo ""
echo "Second YES for step 3..."
curl -s -X POST "$BASE_URL/vlm/callback?user=$USERNAME&procedure_id=pizza_custom@v1&step_id=3&frame_id=frame_007&idem=frame_007" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' | python3 -m json.tool
echo ""
check_status
echo "✅ All steps completed! Procedure is now COMPLETED"
wait_for_user

step 11 "Test Abort (New Procedure)"
echo "Starting new procedure for testing abort..."
curl -s -X POST "$BASE_URL/start_procedure?username=${USERNAME}_abort&procedure_file=app/data/procedures/pizza_custom.json" | python3 -m json.tool
echo ""
echo "Aborting immediately..."
curl -s -X POST "$BASE_URL/abort?username=${USERNAME}_abort" | python3 -m json.tool
echo ""
echo "Checking status..."
curl -s "$BASE_URL/status?username=${USERNAME}_abort" | python3 -m json.tool
echo ""
echo "State should be ABORTED"

echo ""
echo "=========================================="
echo "✅ Test Workflow Completed Successfully!"
echo "=========================================="
echo ""
echo "Summary:"
echo "- Started a 3-step pizza procedure"
echo "- Tested frame ingestion and VLM callbacks"
echo "- Demonstrated debounce (2 consecutive YES needed)"
echo "- Tested pause/resume functionality"
echo "- Tested NO response (resets counter)"
echo "- Completed all 3 steps"
echo "- Tested abort functionality"
echo ""
echo "You can view the API docs at:"
echo "- Swagger UI: $BASE_URL/docs"
echo "- ReDoc: $BASE_URL/redoc"
echo ""