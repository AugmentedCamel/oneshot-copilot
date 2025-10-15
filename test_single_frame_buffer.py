"""Test to verify single-frame buffer behavior."""
import sys
import time
from app.core.statemachine import (
    UserStateMachine,
    ProcedureDef,
    StepDef,
    Decision,
    UserState,
)

# Mock callbacks
on_step_calls = []
on_progress_calls = []
post_to_vlm_calls = []

def mock_on_step(username, procedure_id, step_id, step_name):
    on_step_calls.append((username, procedure_id, step_id, step_name))
    print(f"[OK] on_step called: {username}, step {step_id}: {step_name}")

def mock_on_progress(username, procedure_id, from_step_id, to_step_id):
    on_progress_calls.append((username, procedure_id, from_step_id, to_step_id))
    print(f"[OK] on_progress called: {username}, from step {from_step_id} to {to_step_id}")

def mock_post_to_vlm(frame_id, procedure_id, step_def, username, idem_key):
    post_to_vlm_calls.append((frame_id, procedure_id, step_def, username, idem_key))
    print(f"[OK] VLM request: frame={frame_id}, user={username}, step={step_def['id']}")

# Create state machine
sm = UserStateMachine(
    on_step=mock_on_step,
    on_progress_step=mock_on_progress,
    post_to_vlm=mock_post_to_vlm,
)

# Create a simple test procedure
test_procedure = ProcedureDef(
    id="test@v1",
    name="Test Procedure",
    version=1,
    steps=[
        StepDef(
            id=1,
            name="Step 1",
            positives=["test positive"],
            negatives=["test negative"],
            timeout_s=60,
            debounce_consecutive_yes=2,
        )
    ],
)

print("\n=== TEST 1: Single Frame - No Buffering ===")
sm.start_procedure("testuser", test_procedure)
sm.ingest_frame("testuser", "frame1")
assert len(post_to_vlm_calls) == 1, "Should dispatch frame immediately"
assert post_to_vlm_calls[0][0] == "frame1", "Should dispatch frame1"
print("[OK] Frame dispatched immediately when not inflight")

print("\n=== TEST 2: Frame Buffering During Inflight ===")
post_to_vlm_calls.clear()
sm.start_procedure("testuser2", test_procedure)
sm.ingest_frame("testuser2", "frame1")
assert len(post_to_vlm_calls) == 1, "First frame should dispatch"
print("[OK] First frame dispatched")

# While inflight, ingest more frames - they should buffer (overwriting)
sm.ingest_frame("testuser2", "frame2")
assert len(post_to_vlm_calls) == 1, "Should not dispatch while inflight"
print("[OK] frame2 buffered (not dispatched)")

sm.ingest_frame("testuser2", "frame3")
assert len(post_to_vlm_calls) == 1, "Should not dispatch while inflight"
print("[OK] frame3 buffered (overwrote frame2)")

# Check internal state
user = sm._users["testuser2"]
assert user.buffered_frame == "frame3", "Should have only latest frame buffered"
assert user.inflight == True, "Should still be inflight"
print(f"[OK] Buffer contains only latest frame: {user.buffered_frame}")

print("\n=== TEST 3: Process Buffered Frame After VLM Response ===")
# Simulate VLM response
sm.vlm_decision("testuser2", "frame1", Decision.NO)
assert len(post_to_vlm_calls) == 2, "Should dispatch buffered frame"
assert post_to_vlm_calls[1][0] == "frame3", "Should dispatch frame3 (not frame2)"
print(f"[OK] Buffered frame3 dispatched after VLM response (frame2 was overwritten)")

# Verify buffer is now clear
user = sm._users["testuser2"]
assert user.buffered_frame is None, "Buffer should be cleared after dispatch"
print("[OK] Buffer cleared after dispatching")

print("\n=== TEST 4: Multiple Overwrites ===")
post_to_vlm_calls.clear()
sm.start_procedure("testuser3", test_procedure)
sm.ingest_frame("testuser3", "frame1")
assert len(post_to_vlm_calls) == 1, "First frame dispatched"

# Simulate rapid frame arrivals while inflight
for i in range(2, 10):
    sm.ingest_frame("testuser3", f"frame{i}")

user = sm._users["testuser3"]
assert user.buffered_frame == "frame9", "Should have only the latest frame"
print(f"[OK] After 8 overwrites, buffer contains only: {user.buffered_frame}")

# Complete the inflight request
sm.vlm_decision("testuser3", "frame1", Decision.NO)
assert len(post_to_vlm_calls) == 2, "Should dispatch the buffered frame"
assert post_to_vlm_calls[1][0] == "frame9", "Should dispatch frame9"
print("[OK] Only frame9 was dispatched (frames 2-8 were overwritten)")

print("\n=== All Tests Passed! ===")
print("\nSUMMARY:")
print("- Single-frame buffer implemented successfully")
print("- New frames overwrite buffered frame when inflight")
print("- Only the most recent frame is processed after VLM response")
print("- No queueing of multiple frames - reduces latency")