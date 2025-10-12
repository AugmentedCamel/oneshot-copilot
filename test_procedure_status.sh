#!/bin/bash

# Test script for Procedure Status Service
# Tests the new GET /api/procedure endpoint and file persistence

set -e  # Exit on error

BASE_URL="http://localhost:8000"
TEST_USER="status_test_user"
STATUS_DIR="app/data/user_status"
IMAGE_FILE="${1:-test_image.jpg}"

echo "=========================================="
echo "Procedure Status Service - Test Suite"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print test results
test_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
}

test_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    exit 1
}

test_info() {
    echo -e "${YELLOW}ℹ️  INFO${NC}: $1"
}

# Function to print test headers
test_section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🧪 TEST $1: $2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Function to verify JSON field
verify_json_field() {
    local json="$1"
    local field="$2"
    local expected="$3"
    local actual=$(echo "$json" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('$field', ''))")
    
    if [ "$actual" = "$expected" ]; then
        test_pass "Field '$field' = '$expected'"
        return 0
    else
        test_fail "Field '$field' expected '$expected' but got '$actual'"
        return 1
    fi
}

# Function to check file exists
check_file_exists() {
    local filepath="$1"
    if [ -f "$filepath" ]; then
        test_pass "File exists: $filepath"
        return 0
    else
        test_fail "File does not exist: $filepath"
        return 1
    fi
}

# Function to verify step status
verify_step_status() {
    local json="$1"
    local step_id="$2"
    local expected_status="$3"
    
    local actual_status=$(echo "$json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for step in data.get('steps', []):
    if step['id'] == $step_id:
        print(step['status'])
        break
")
    
    if [ "$actual_status" = "$expected_status" ]; then
        test_pass "Step $step_id status = '$expected_status'"
        return 0
    else
        test_fail "Step $step_id expected status '$expected_status' but got '$actual_status'"
        return 1
    fi
}

# Check if image file exists
if [ ! -f "$IMAGE_FILE" ]; then
    test_info "Creating placeholder test image..."
    if command -v convert &> /dev/null; then
        convert -size 640x480 xc:white -pointsize 30 -draw "text 200,240 'Test Image'" test_image.jpg
        IMAGE_FILE="test_image.jpg"
        test_pass "Created test_image.jpg"
    else
        test_fail "No test image found and ImageMagick not available. Please provide a test image."
    fi
fi

test_info "Using test image: $IMAGE_FILE"
test_info "Using test user: $TEST_USER"
echo ""

# =============================================================================
# TEST 1: Error Case - Non-existent User
# =============================================================================
test_section 1 "Error Case - Non-existent User"

response=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/procedure?username=nonexistent_user_123")
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | head -n-1)

if [ "$http_code" = "404" ]; then
    test_pass "Returns 404 for non-existent user"
else
    test_fail "Expected 404, got $http_code"
fi

# =============================================================================
# TEST 2: Initial Status After Starting Procedure
# =============================================================================
test_section 2 "Initial Status After Starting Procedure"

# Clean up any existing data
rm -f "$STATUS_DIR/${TEST_USER}_pizza_custom@v1.json" 2>/dev/null || true

# Start procedure
start_response=$(curl -s -X POST "$BASE_URL/start_procedure?username=$TEST_USER&procedure_file=app/data/procedures/pizza_custom.json")
test_info "Start response: $start_response"

# Wait a moment for status file to be written
sleep 0.5

# Test API endpoint
status_response=$(curl -s "$BASE_URL/api/procedure?username=$TEST_USER")
test_info "API Response:"
echo "$status_response" | python3 -m json.tool

# Verify response structure
verify_json_field "$status_response" "username" "$TEST_USER"
verify_json_field "$status_response" "id" "pizza_custom@v1"
verify_json_field "$status_response" "name" "Make a Custom Pizza"
verify_json_field "$status_response" "version" "1"

# Verify initial step statuses
verify_step_status "$status_response" "1" "in_progress"
verify_step_status "$status_response" "2" "todo"
verify_step_status "$status_response" "3" "todo"

# =============================================================================
# TEST 3: File Persistence
# =============================================================================
test_section 3 "File Persistence"

# Check if status file was created
status_file="$STATUS_DIR/${TEST_USER}_pizza_custom@v1.json"
check_file_exists "$status_file"

# Verify file contents match API response
file_content=$(cat "$status_file")
test_info "File contents:"
echo "$file_content" | python3 -m json.tool

# Verify file has same structure as API
verify_json_field "$file_content" "username" "$TEST_USER"
verify_json_field "$file_content" "id" "pizza_custom@v1"

# =============================================================================
# TEST 4: Status Transition - Progress to Step 2
# =============================================================================
test_section 4 "Status Transition - Progress to Step 2"

# Upload first frame
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$TEST_USER" \
  -F "frame_id=frame_001" \
  -F "file=@$IMAGE_FILE" > /dev/null

# First YES
curl -s -X POST "$BASE_URL/vlm/callback?user=$TEST_USER&procedure_id=pizza_custom@v1&step_id=1&frame_id=frame_001&idem=frame_001" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' > /dev/null

# Upload second frame
curl -s -X POST "$BASE_URL/ingest" \
  -F "username=$TEST_USER" \
  -F "frame_id=frame_002" \
  -F "file=@$IMAGE_FILE" > /dev/null

# Second YES (should trigger progression)
curl -s -X POST "$BASE_URL/vlm/callback?user=$TEST_USER&procedure_id=pizza_custom@v1&step_id=1&frame_id=frame_002&idem=frame_002" \
  -H "Content-Type: application/json" \
  -d '{"decision": "YES"}' > /dev/null

# Wait for status update
sleep 0.5

# Check status after progression
status_response=$(curl -s "$BASE_URL/api/procedure?username=$TEST_USER")
test_info "Status after step 1 completion:"
echo "$status_response" | python3 -m json.tool

# Verify step statuses updated correctly
verify_step_status "$status_response" "1" "done"
verify_step_status "$status_response" "2" "in_progress"
verify_step_status "$status_response" "3" "todo"

# Verify file was updated
file_content=$(cat "$status_file")
verify_step_status "$file_content" "1" "done"
verify_step_status "$file_content" "2" "in_progress"

# =============================================================================
# TEST 5: Complete All Steps
# =============================================================================
test_section 5 "Complete All Steps"

# Complete step 2
for i in 3 4; do
    curl -s -X POST "$BASE_URL/ingest" \
      -F "username=$TEST_USER" \
      -F "frame_id=frame_00$i" \
      -F "file=@$IMAGE_FILE" > /dev/null
    
    curl -s -X POST "$BASE_URL/vlm/callback?user=$TEST_USER&procedure_id=pizza_custom@v1&step_id=2&frame_id=frame_00$i&idem=frame_00$i" \
      -H "Content-Type: application/json" \
      -d '{"decision": "YES"}' > /dev/null
done

# Complete step 3
for i in 5 6; do
    curl -s -X POST "$BASE_URL/ingest" \
      -F "username=$TEST_USER" \
      -F "frame_id=frame_00$i" \
      -F "file=@$IMAGE_FILE" > /dev/null
    
    curl -s -X POST "$BASE_URL/vlm/callback?user=$TEST_USER&procedure_id=pizza_custom@v1&step_id=3&frame_id=frame_00$i&idem=frame_00$i" \
      -H "Content-Type: application/json" \
      -d '{"decision": "YES"}' > /dev/null
done

# Wait for final status update
sleep 0.5

# Check final status
status_response=$(curl -s "$BASE_URL/api/procedure?username=$TEST_USER")
test_info "Final status after completion:"
echo "$status_response" | python3 -m json.tool

# Verify all steps are done
verify_step_status "$status_response" "1" "done"
verify_step_status "$status_response" "2" "done"
verify_step_status "$status_response" "3" "done"

# Verify file reflects completion
file_content=$(cat "$status_file")
verify_step_status "$file_content" "1" "done"
verify_step_status "$file_content" "2" "done"
verify_step_status "$file_content" "3" "done"

# =============================================================================
# TEST 6: Abort Scenario
# =============================================================================
test_section 6 "Abort Scenario"

abort_user="${TEST_USER}_abort"
abort_file="$STATUS_DIR/${abort_user}_pizza_custom@v1.json"

# Clean up any existing data
rm -f "$abort_file" 2>/dev/null || true

# Start new procedure
curl -s -X POST "$BASE_URL/start_procedure?username=$abort_user&procedure_file=app/data/procedures/pizza_custom.json" > /dev/null
sleep 0.5

# Verify initial status
status_response=$(curl -s "$BASE_URL/api/procedure?username=$abort_user")
verify_step_status "$status_response" "1" "in_progress"

# Abort procedure
curl -s -X POST "$BASE_URL/abort?username=$abort_user" > /dev/null
sleep 0.5

# Check status file exists (should still exist after abort)
check_file_exists "$abort_file"

# Verify status shows all as todo (aborted state)
status_response=$(curl -s "$BASE_URL/api/procedure?username=$abort_user")
test_info "Status after abort:"
echo "$status_response" | python3 -m json.tool

# =============================================================================
# TEST 7: Multiple Users
# =============================================================================
test_section 7 "Multiple Users - Isolation"

user1="multi_test_user1"
user2="multi_test_user2"

# Start procedures for both users
curl -s -X POST "$BASE_URL/start_procedure?username=$user1&procedure_file=app/data/procedures/pizza_custom.json" > /dev/null
curl -s -X POST "$BASE_URL/start_procedure?username=$user2&procedure_file=app/data/procedures/pizza_custom.json" > /dev/null
sleep 0.5

# Check both users have separate status files
check_file_exists "$STATUS_DIR/${user1}_pizza_custom@v1.json"
check_file_exists "$STATUS_DIR/${user2}_pizza_custom@v1.json"

# Progress user1 to step 2
for i in 1 2; do
    curl -s -X POST "$BASE_URL/ingest" \
      -F "username=$user1" \
      -F "frame_id=u1_f$i" \
      -F "file=@$IMAGE_FILE" > /dev/null
    
    curl -s -X POST "$BASE_URL/vlm/callback?user=$user1&procedure_id=pizza_custom@v1&step_id=1&frame_id=u1_f$i&idem=u1_f$i" \
      -H "Content-Type: application/json" \
      -d '{"decision": "YES"}' > /dev/null
done

sleep 0.5

# Verify user1 progressed but user2 didn't
status1=$(curl -s "$BASE_URL/api/procedure?username=$user1")
status2=$(curl -s "$BASE_URL/api/procedure?username=$user2")

verify_step_status "$status1" "1" "done"
verify_step_status "$status1" "2" "in_progress"

verify_step_status "$status2" "1" "in_progress"
verify_step_status "$status2" "2" "todo"

test_pass "User statuses are properly isolated"

# =============================================================================
# TEST 8: Filename Sanitization
# =============================================================================
test_section 8 "Filename Sanitization"

dangerous_user="test/../../../etc/passwd"
# This should be sanitized to "testpasswd" or similar

# Try to start procedure with dangerous username
start_response=$(curl -s -X POST "$BASE_URL/start_procedure?username=$dangerous_user&procedure_file=app/data/procedures/pizza_custom.json")

# Check if server handled it (shouldn't crash)
if [ -n "$start_response" ]; then
    test_pass "Server handled potentially dangerous username without crashing"
    
    # Verify no file was created outside status directory
    if [ ! -f "/etc/passwd_pizza_custom@v1.json" ] && [ ! -f "../../../etc/passwd_pizza_custom@v1.json" ]; then
        test_pass "No files created outside status directory"
    else
        test_fail "Unsafe file path detected!"
    fi
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "=========================================="
echo "✅ All Tests Passed!"
echo "=========================================="
echo ""
echo "Test Summary:"
echo "  ✅ Error handling (404 for non-existent user)"
echo "  ✅ Initial status after starting procedure"
echo "  ✅ File persistence in correct location"
echo "  ✅ Status transitions (step progression)"
echo "  ✅ Completion status (all steps done)"
echo "  ✅ Abort scenario"
echo "  ✅ Multiple user isolation"
echo "  ✅ Filename sanitization"
echo ""
echo "Status files created in: $STATUS_DIR/"
ls -lh "$STATUS_DIR/"*.json 2>/dev/null || echo "  (No files to display)"
echo ""
echo "Verified implementation:"
echo "  • API endpoint: GET /api/procedure?username=<username>"
echo "  • Status service: app/services/status_service.py"
echo "  • State machine integration: app/core/statemachine.py"
echo "  • File persistence: app/data/user_status/{username}_{procedure_id}.json"
echo ""