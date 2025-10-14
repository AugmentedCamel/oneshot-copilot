# VLM Response Bug Fix Summary

## Problem Description

The system was experiencing an infinite loop where VLM responses of "yes" were being interpreted as "NO", causing the same frame to be reprocessed repeatedly (~20+ times).

## Root Causes Identified

### 1. **Response Parsing Issue**
- **Location**: [`app/core/callbacks.py:131-141`](app/core/callbacks.py:131-141)
- **Issue**: The code expected a nested response structure `{"data": {"result": "yes"}}`, but VLM was potentially returning a flat structure `{"result": "yes"}`
- **Result**: `result` was `None`, triggering the default `Decision.NO` fallback

### 2. **Recursive Resubmission Loop**
- **Location**: [`app/core/statemachine.py:386-422`](app/core/statemachine.py:386-422)
- **Issue**: After processing a frame:
  1. Frame was cleared from FrameStore
  2. But frame_id remained in user's FrameBuffer
  3. State machine saw `inflight=False` + non-empty buffer
  4. Dispatched the same frame again → infinite cycle
- **Trigger**: Frame cleared from store but `inflight_frame_id` was reset to `None` immediately after processing, preventing deduplication

### 3. **Frame Clearing Race Condition**
- **Location**: [`app/core/frame_store.py:31-38`](app/core/frame_store.py:31-38)
- **Issue**: Multiple redundant clear requests for the same frame_id without synchronization

## Fixes Applied

### Fix 1: Enhanced VLM Response Parsing
**File**: [`app/core/callbacks.py`](app/core/callbacks.py:128-165)

**Changes**:
- Added support for both nested and flat response formats
- Enhanced diagnostic logging to capture raw response structure
- Improved string parsing to handle variations: "yes", "true", "1" → `Decision.YES`
- Added type checking and better error handling

```python
# Try nested format first: {"data": {"result": "yes"}}
data = response_json.get("data") if isinstance(response_json, dict) else None
if data and isinstance(data, dict):
    result = data.get("result")
    # ...
else:
    # Fall back to flat format: {"result": "yes"}
    result = response_json.get("result") if isinstance(response_json, dict) else None
```

### Fix 2: Buffer Deduplication
**File**: [`app/core/statemachine.py`](app/core/statemachine.py:406-415)

**Changes**:
- Added check to prevent redispatching the same frame
- If `frame_id == inflight_frame_id`, skip dispatch and remove frame from buffer
- Allows system to continue with new frames

```python
# CRITICAL: Prevent redispatching the same frame (buffer deduplication)
if frame_id == u.inflight_frame_id:
    logger.warning(f"[STATE_MACHINE] *** SKIPPING REDISPATCH *** - frame_id={frame_id} already processed")
    # Remove processed frame from buffer
    u.frame_buffer = deque([fid for fid in u.frame_buffer if fid != frame_id], maxlen=u.frame_buffer.maxlen)
    return
```

### Fix 3: Synchronized Frame Clearing
**File**: [`app/core/frame_store.py`](app/core/frame_store.py:31-48)

**Changes**:
- Added guard against redundant clear requests
- Returns boolean to indicate if frame was actually cleared
- Enhanced logging for better debugging

```python
def clear_frame(frame_id: str) -> bool:
    # Guard against redundant clear requests
    if frame_id not in _frame_store:
        logger.warning(f"[FRAME_STORE] Ignoring redundant clear request - frame_id={frame_id}")
        return False
    # ... clear logic
    return True
```

### Fix 4: Smart inflight_frame_id Management
**File**: [`app/core/statemachine.py`](app/core/statemachine.py:306-335)

**Changes**:
- Keep `inflight_frame_id` set after processing to enable deduplication
- Only clear `inflight_frame_id` when:
  - Progressing to a new step (old frame no longer relevant)
  - Procedure completes

```python
# After VLM response
u.inflight = False
u.inflight_since_ms = None
# DO NOT clear inflight_frame_id here - used for deduplication

# Clear only on step progression
if next_index < len(u.procedure.steps):
    u.inflight_frame_id = None  # New step, old frame irrelevant
```

## Expected Behavior After Fixes

1. **Correct YES/NO Parsing**: VLM responses with `{"result": "yes"}` will be correctly parsed as `Decision.YES`
2. **No Infinite Loops**: Each frame is processed exactly once; redispatch is prevented
3. **Clean Frame Management**: Frames are cleared once and redundant clears are ignored
4. **Proper Progression**: YES responses correctly increment consecutive counter and progress steps

## Testing Recommendations

1. Test with VLM returning flat format: `{"result": "yes"}`
2. Test with VLM returning nested format: `{"data": {"result": "yes"}}`
3. Verify no frame redispatch in logs (look for "SKIPPING REDISPATCH" messages)
4. Confirm step progression occurs on consecutive YES responses
5. Check logs for "✓ Decision parsed: 'yes' -> YES" success messages

## Files Modified

1. [`app/core/callbacks.py`](app/core/callbacks.py) - Enhanced response parsing
2. [`app/core/statemachine.py`](app/core/statemachine.py) - Buffer deduplication & inflight management  
3. [`app/core/frame_store.py`](app/core/frame_store.py) - Synchronized clearing

## Log Markers to Monitor

- `[CALLBACK] ✓ Decision parsed: 'yes' -> YES` - Successful YES parsing
- `[STATE_MACHINE] *** SKIPPING REDISPATCH ***` - Deduplication working
- `[FRAME_STORE] ✓ Frame cleared` - Successful frame cleanup
- `[FRAME_STORE] Ignoring redundant clear request` - Prevented race condition