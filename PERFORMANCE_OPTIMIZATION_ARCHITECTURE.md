# Performance Optimization Architecture
## VLM-Based State Machine Throughput Improvements

**Document Version:** 1.0  
**Date:** 2025-10-16  
**Status:** Design Phase - Ready for Implementation

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Current Architecture Analysis](#current-architecture-analysis)
3. [Identified Bottlenecks](#identified-bottlenecks)
4. [Proposed Optimizations](#proposed-optimizations)
5. [Detailed Design](#detailed-design)
6. [Implementation Plan](#implementation-plan)
7. [Risks and Mitigations](#risks-and-mitigations)
8. [Success Metrics](#success-metrics)

---

## Executive Summary

This document outlines a comprehensive performance optimization plan for the Oneshot Copilot VLM-based state machine application. The current system experiences low throughput due to connection overhead, synchronous blocking, and inefficient timeout handling.

**Key Optimizations:**
1. **Connection Pooling**: Singleton httpx client with persistent connections (~1s latency reduction)
2. **Async Queue Architecture**: Decouple frame ingestion from VLM processing (immediate API response)
3. **Timeout Adjustments**: Increase to 2000-2500ms, align httpx timeout (reduce false timeouts)
4. **Detailed Metrics**: Add queue_wait_ms, http_post_ms, server_proc_ms tracking
5. **Model Optimization**: Image resize/crop before VLM submission

**Expected Improvements:**
- **Throughput**: 2-3x increase (from ~1 frame/sec to 2-3 frames/sec)
- **API Latency**: 90% reduction (from ~100-500ms to <10ms)
- **Connection Overhead**: Eliminate ~1s TCP/SSL handshake per request
- **Reliability**: Reduce false timeouts by 80%

---

## Current Architecture Analysis

### System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    CURRENT ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────┘

[Client] 
   │
   │ POST /api/ingest
   ↓
┌──────────────────────┐
│  API Ingest Handler  │ ← [BLOCKS until frame stored]
│  (app/api/ingest.py) │
└──────────────────────┘
   │
   │ machine.ingest_frame()
   ↓
┌──────────────────────┐
│   State Machine      │
│  (statemachine.py)   │ ← [Checks inflight status]
└──────────────────────┘
   │
   │ if not inflight
   ↓
┌──────────────────────┐
│  _maybe_dispatch()   │ ← [Creates async task]
└──────────────────────┘
   │
   │ asyncio.create_task()
   ↓
┌──────────────────────────────────────────┐
│  post_to_vlm_callback()                  │
│  (app/core/callbacks.py)                 │
└──────────────────────────────────────────┘
   │
   │ 1. get_frame(frame_id)
   ↓
┌──────────────────────────────────────────┐
│  post_to_vlm_multipart()                 │
│  (app/core/vlm_client.py)                │
│                                           │
│  ⚠️  BOTTLENECK: Creates new client      │
│      async with httpx.AsyncClient(...)   │
│      - New SSL context (~200-500ms)      │
│      - New TCP handshake (~100-300ms)    │
│      - No connection reuse               │
└──────────────────────────────────────────┘
   │
   │ HTTP POST to VLM
   ↓
[VLM Service]
   │
   │ Response
   ↓
┌──────────────────────┐
│ machine.vlm_decision │ ← [Process response]
└──────────────────────┘
   │
   │ if buffered_frame exists
   ↓
[Dispatch buffered frame] ← [Single frame buffer, overwrite semantics]
```

### Key Components

#### 1. Frame Ingestion ([`app/api/ingest.py`](app/api/ingest.py:13-69))
- **Function**: Receives frames via POST endpoint
- **Current Behavior**: 
  - Reads frame bytes (await file.read())
  - Stores in memory via [`store_frame()`](app/core/frame_store.py)
  - Calls [`machine.ingest_frame()`](app/core/statemachine.py:275-308)
  - Returns success response
- **Latency**: 50-100ms (including state machine call)
- **Issue**: API blocks on state machine processing

#### 2. State Machine ([`app/core/statemachine.py`](app/core/statemachine.py:98-502))
- **Function**: Manages user workflows and VLM dispatch
- **Current Behavior**:
  - Single inflight request per user
  - Single buffered frame (overwrite on new frame)
  - 1000ms VLM request timeout (line 413)
  - Dispatches immediately if not inflight
- **Issue**: Timeout too short, clears inflight before actual failure

#### 3. VLM Client ([`app/core/vlm_client.py`](app/core/vlm_client.py:11-90))
- **Function**: HTTP communication with VLM service
- **Current Behavior**:
  - Creates new [`httpx.AsyncClient`](app/core/vlm_client.py:58) per request
  - Timeout: 30.0 seconds
  - Multipart form data upload
- **CRITICAL BOTTLENECK**: No connection pooling
  - SSL handshake: ~200-500ms
  - TCP handshake: ~100-300ms
  - Total overhead: ~1000ms per request

#### 4. Stream Quality Filter ([`app/services/stream_quality_filter.py`](app/services/stream_quality_filter.py))
- **Function**: RTSP stream processing and frame filtering
- **Current Behavior**:
  - Uses `requests` library (not httpx)
  - Creates new connection per POST
  - Has good timing metrics (lines 218-238)
- **Issue**: Not using shared connection pool

### Current Performance Metrics

**Measured Latencies** (from logs):
- Frame ingest API: 50-100ms
- State machine dispatch: 10-20ms
- VLM callback total: 1500-2500ms
  - Frame retrieval: <5ms
  - HTTP POST: 1000-1500ms (includes connection overhead)
  - VLM processing: 500-800ms
  - Response parsing: <5ms

**Throughput**:
- Current: ~1 frame per 1.5-2 seconds
- Theoretical max (without optimization): 0.5-0.67 fps
- Primary bottleneck: Connection overhead (~1s) + VLM processing (~0.5-0.8s)

---

## Identified Bottlenecks

### 1. Connection Pooling (CRITICAL - Highest Impact)

**Location**: [`app/core/vlm_client.py`](app/core/vlm_client.py:58)

**Problem**:
```python
async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.post(...)
```

**Impact**:
- Creates new client for every request
- Establishes new SSL context: ~200-500ms
- Performs TCP handshake: ~100-300ms
- Total overhead: ~1000ms per request
- No connection reuse
- No HTTP/2 multiplexing benefits

**Evidence**:
- User requirements state: "Currently rebuilding SSL context + TCP handshake each call (~1s gap)"
- This is the primary throughput limiter

**Solution Impact**: Eliminates ~1s per request = 50-67% latency reduction

---

### 2. Timeout Configuration Mismatch

**Location**: 
- [`app/core/statemachine.py`](app/core/statemachine.py:413): VLM timeout = 1000ms
- [`app/core/vlm_client.py`](app/core/vlm_client.py:58): httpx timeout = 30000ms

**Problem**:
- State machine clears inflight after 1s
- But HTTP request still running (30s timeout)
- VLM actually needs 500-800ms to process
- With 1s connection overhead, total time is 1500-1800ms
- State machine times out at 1000ms - too early!

**Impact**:
- False timeouts cause:
  - Wasted VLM processing (request completes but result ignored)
  - Frame buffer corruption (new frame dispatched while old request still running)
  - Reduced throughput (unnecessary retries)

**Evidence**:
- Log shows: "VLM REQUEST TIMEOUT" even when VLM service is responsive
- Total processing time 1500-2500ms but timeout at 1000ms

**Requirements**: 
- Increase state machine timeout to 2000-2500ms
- Align httpx timeout to 2.5s (slightly higher than state machine)

---

### 3. Synchronous Blocking Architecture

**Location**: [`app/api/ingest.py`](app/api/ingest.py:13-69)

**Problem**:
```python
@router.post("/ingest")
async def ingest(...):
    frame_bytes = await file.read()  # ← blocks on I/O
    store_frame(frame_id, frame_bytes)  # ← synchronous
    machine.ingest_frame(username, frame_id)  # ← synchronous (but creates async task)
    return {"ok": True, "queued": True}
```

**Impact**:
- Client waits for frame storage and state machine logic
- API response time: 50-100ms
- Coupled ingestion and processing
- Cannot buffer multiple frames efficiently
- Stream quality filter waits for API response

**Requirements**: 
- POST thread should return immediately (<10ms)
- Use bounded async queue
- Separate worker pulls from queue
- If queue full, drop/replace oldest frame

---

### 4. Insufficient Timing Metrics

**Current State**:
- Some timing exists but scattered
- Not granular enough for bottleneck identification
- Missing key metrics

**Missing Metrics**:
1. **queue_wait_ms**: Time from enqueue → dequeue
2. **http_post_ms**: Socket connect → 200 OK response
3. **server_proc_ms**: VLM server processing time (from response headers)

**Requirements**:
- Add three separate timings in stream_quality_filter
- Consistent metric collection across all paths
- Easy to identify which component is slow

---

### 5. Model Optimization

**Current State**:
- Sending full-resolution images to VLM
- No resize/crop before submission
- Unknown if Moondream crop/tiling is optimal

**Requirements**:
- Verify Moondream crop/tiling settings
- Set smallest settings that still answer questions
- Ensure image resize matches model's expected size before send
- Target: Reduce image size by 50-75% → faster upload, faster VLM processing

**Potential Impact**: 
- Smaller images → faster upload (20-30% reduction)
- Faster VLM processing (10-20% reduction)
- Total: ~30-50% improvement in VLM roundtrip

---

## Proposed Optimizations

### Optimization 1: Singleton httpx Client with Connection Pooling

**Goal**: Eliminate connection overhead (~1s per request)

**Design**:
```python
# app/core/vlm_client.py
from typing import Optional
import httpx

# Global singleton client
_global_client: Optional[httpx.AsyncClient] = None

async def get_vlm_client() -> httpx.AsyncClient:
    """Get or create the global VLM HTTP client."""
    global _global_client
    if _global_client is None or _global_client.is_closed:
        _global_client = httpx.AsyncClient(
            timeout=httpx.Timeout(2.5, connect=5.0),  # 2.5s total, 5s connect
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=30.0
            ),
            http2=True  # Enable HTTP/2 for multiplexing
        )
    return _global_client

async def close_vlm_client():
    """Close the global VLM client."""
    global _global_client
    if _global_client is not None:
        await _global_client.aclose()
        _global_client = None
```

**Integration**:
- Initialize in [`app/main.py`](app/main.py:150-169) startup event
- Close in shutdown event
- Use in [`post_to_vlm_multipart()`](app/core/vlm_client.py:11-90)

**Benefits**:
- Persistent connections: No SSL/TCP overhead
- Connection pooling: Reuse across requests
- HTTP/2: Multiplexing support
- Latency reduction: ~1000ms → ~100ms for subsequent requests

---

### Optimization 2: Async Queue Architecture

**Goal**: Decouple ingestion from VLM processing, return immediately

**Design**:

```
┌────────────────────────────────────────────────────────────┐
│              NEW QUEUE-BASED ARCHITECTURE                   │
└────────────────────────────────────────────────────────────┘

[Client]
   │
   │ POST /api/ingest
   ↓
┌──────────────────────┐
│  API Ingest Handler  │ ← [Returns immediately <10ms]
└──────────────────────┘
   │
   │ queue.put_nowait() (or replace oldest if full)
   ↓
┌──────────────────────────────────────────────┐
│     AsyncQueue (bounded, size=10)            │
│  - If full: drop oldest, add newest          │
│  - Only keep freshest frames                 │
└──────────────────────────────────────────────┘
   │
   │ Background worker pulls
   ↓
┌──────────────────────┐
│  VLM Worker Task     │ ← [Dedicated async task]
│  - Pulls from queue  │
│  - Calls state       │
│    machine           │
└──────────────────────┘
   │
   │ (existing flow)
   ↓
[VLM Processing...]
```

**Implementation**:
```python
# app/core/frame_queue.py (NEW FILE)
import asyncio
from dataclasses import dataclass
from typing import Optional
from time import perf_counter

@dataclass
class QueuedFrame:
    username: str
    frame_id: str
    enqueue_time: float  # perf_counter() timestamp
    
class FrameQueue:
    def __init__(self, maxsize: int = 10):
        self._queue = asyncio.Queue(maxsize=maxsize)
        self._stats = {
            'enqueued': 0,
            'dequeued': 0,
            'dropped': 0
        }
    
    async def enqueue(self, frame: QueuedFrame) -> bool:
        """Enqueue frame, drop oldest if full."""
        if self._queue.full():
            try:
                dropped = self._queue.get_nowait()
                self._stats['dropped'] += 1
                logger.warning(f"Queue full, dropped frame: {dropped.frame_id}")
            except asyncio.QueueEmpty:
                pass
        
        await self._queue.put(frame)
        self._stats['enqueued'] += 1
        return True
    
    async def dequeue(self, timeout: Optional[float] = None) -> Optional[QueuedFrame]:
        """Dequeue next frame."""
        try:
            frame = await asyncio.wait_for(
                self._queue.get(), 
                timeout=timeout
            )
            self._stats['dequeued'] += 1
            return frame
        except asyncio.TimeoutError:
            return None
```

**Integration Points**:
1. Create queue in [`app/main.py`](app/main.py:150-169) startup
2. Modify [`app/api/ingest.py`](app/api/ingest.py:13-69) to enqueue instead of direct call
3. Add background worker task to process queue
4. Worker calls existing state machine flow

**Benefits**:
- API response: 50-100ms → <10ms (95% reduction)
- Better buffering: Queue of 10 vs single frame
- Smart dropping: Keep freshest frames
- Decoupled: Client doesn't wait for VLM

---

### Optimization 3: Timeout Adjustments

**Changes**:

1. **State Machine Timeout**: 1000ms → 2000-2500ms
   - Location: [`app/core/statemachine.py`](app/core/statemachine.py:413)
   - Change: `if elapsed_ms > 2500:` (was 1000)

2. **httpx Client Timeout**: 30s → 2.5s
   - Location: [`app/core/vlm_client.py`](app/core/vlm_client.py:58)
   - Change: `timeout=httpx.Timeout(2.5, connect=5.0)`

3. **Don't Clear Inflight Until True Timeout**:
   - Keep inflight_frame_id for deduplication
   - Only clear on actual HTTP error or timeout
   - Current issue: Clears too early, allows redispatch

**Configuration**:
```python
# app/config.py
class Settings(BaseSettings):
    # ... existing settings ...
    VLM_REQUEST_TIMEOUT_MS: int = 2500  # State machine timeout
    VLM_HTTP_TIMEOUT_S: float = 2.5     # HTTP client timeout
```

**Benefits**:
- Eliminate false timeouts
- Proper alignment between layers
- Better error handling
- Reduced wasted VLM processing

---

### Optimization 4: Detailed Timing Metrics

**Implementation**:

```python
# app/core/metrics.py (NEW FILE)
from dataclasses import dataclass, field
from time import perf_counter
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class VLMRequestMetrics:
    """Detailed metrics for a single VLM request."""
    frame_id: str
    username: str
    
    # Timing checkpoints (perf_counter timestamps)
    enqueue_time: Optional[float] = None
    dequeue_time: Optional[float] = None
    http_start_time: Optional[float] = None
    http_response_time: Optional[float] = None
    vlm_processing_ms: Optional[float] = None  # From VLM response headers
    
    @property
    def queue_wait_ms(self) -> Optional[float]:
        """Time from enqueue to dequeue."""
        if self.enqueue_time and self.dequeue_time:
            return (self.dequeue_time - self.enqueue_time) * 1000
        return None
    
    @property
    def http_post_ms(self) -> Optional[float]:
        """Time from HTTP start to 200 OK response."""
        if self.http_start_time and self.http_response_time:
            return (self.http_response_time - self.http_start_time) * 1000
        return None
    
    @property
    def server_proc_ms(self) -> Optional[float]:
        """VLM server processing time (from response headers)."""
        return self.vlm_processing_ms
    
    @property
    def total_ms(self) -> float:
        """Total time from enqueue to completion."""
        total = 0.0
        if self.queue_wait_ms:
            total += self.queue_wait_ms
        if self.http_post_ms:
            total += self.http_post_ms
        return total
    
    def log_summary(self):
        """Log all timing metrics."""
        logger.info(f"[METRICS] ===== VLM Request Metrics =====")
        logger.info(f"[METRICS] frame_id: {self.frame_id}")
        logger.info(f"[METRICS] username: {self.username}")
        logger.info(f"[METRICS] queue_wait_ms: {self.queue_wait_ms:.2f}ms" if self.queue_wait_ms else "[METRICS] queue_wait_ms: N/A")
        logger.info(f"[METRICS] http_post_ms: {self.http_post_ms:.2f}ms" if self.http_post_ms else "[METRICS] http_post_ms: N/A")
        logger.info(f"[METRICS] server_proc_ms: {self.server_proc_ms:.2f}ms" if self.server_proc_ms else "[METRICS] server_proc_ms: N/A")
        logger.info(f"[METRICS] total_ms: {self.total_ms:.2f}ms")
        logger.info(f"[METRICS] ============================")
```

**Integration**:
1. Create metrics object when enqueuing frame
2. Update timestamps at each checkpoint:
   - Enqueue: `enqueue_time = perf_counter()`
   - Dequeue: `dequeue_time = perf_counter()`
   - HTTP start: `http_start_time = perf_counter()`
   - HTTP response: `http_response_time = perf_counter()`
   - Extract VLM time from response headers
3. Log summary after request completion

**Stream Quality Filter Integration**:
- Add same timing points in [`app/services/stream_quality_filter.py`](app/services/stream_quality_filter.py:665-782)
- Track queue_wait_ms, http_post_ms, server_proc_ms
- Integrate with existing timing_stats dictionary

---

### Optimization 5: Model Optimization

**Investigation Required**:
1. Determine current image dimensions sent to VLM
2. Check Moondream model's optimal input size
3. Test different crop/tiling configurations
4. Measure impact on accuracy vs performance

**Proposed Changes**:

```python
# app/core/image_optimizer.py (NEW FILE)
import cv2
import numpy as np
from typing import Tuple
import logging

logger = logging.getLogger(__name__)

class ImageOptimizer:
    """Optimize images before VLM submission."""
    
    def __init__(
        self,
        target_width: int = 640,
        target_height: int = 480,
        jpeg_quality: int = 85
    ):
        self.target_width = target_width
        self.target_height = target_height
        self.jpeg_quality = jpeg_quality
        logger.info(f"ImageOptimizer initialized - target: {target_width}x{target_height}, quality: {jpeg_quality}")
    
    def optimize_frame(self, frame_bytes: bytes) -> bytes:
        """Resize and compress frame for optimal VLM processing."""
        # Decode image
        nparr = np.frombuffer(frame_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise ValueError("Failed to decode image")
        
        original_size = len(frame_bytes)
        h, w = img.shape[:2]
        
        # Resize if larger than target
        if w > self.target_width or h > self.target_height:
            # Maintain aspect ratio
            scale = min(
                self.target_width / w,
                self.target_height / h
            )
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            logger.debug(f"Resized image: {w}x{h} -> {new_w}x{new_h}")
        
        # Re-encode with target quality
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        success, encoded = cv2.imencode('.jpg', img, encode_param)
        
        if not success:
            raise RuntimeError("Failed to encode optimized image")
        
        optimized_bytes = encoded.tobytes()
        optimized_size = len(optimized_bytes)
        reduction_pct = (1 - optimized_size / original_size) * 100
        
        logger.info(f"Image optimized: {original_size} -> {optimized_size} bytes ({reduction_pct:.1f}% reduction)")
        
        return optimized_bytes
```

**Configuration**:
```python
# app/config.py
class Settings(BaseSettings):
    # ... existing ...
    VLM_IMAGE_MAX_WIDTH: int = 640
    VLM_IMAGE_MAX_HEIGHT: int = 480
    VLM_IMAGE_QUALITY: int = 85
    ENABLE_IMAGE_OPTIMIZATION: bool = True
```

**Integration**:
- Optimize in [`post_to_vlm_multipart()`](app/core/vlm_client.py:11-90) before sending
- Or optimize when storing in frame_store
- Log original vs optimized size

**Expected Impact**:
- Image size reduction: 50-75%
- Upload time reduction: 30-50%
- VLM processing: 10-20% faster
- Total: ~40% improvement in VLM roundtrip

---

## Detailed Design

### Component Architecture (OPTIMIZED)

```
┌────────────────────────────────────────────────────────────────────┐
│                    OPTIMIZED ARCHITECTURE                           │
└────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐
│   FastAPI Startup   │
│   (app/main.py)     │
└─────────────────────┘
         │
         ├─→ Initialize singleton httpx client (connection pooling)
         ├─→ Create frame queue (bounded, size=10)
         └─→ Start VLM worker background task
         
┌─────────────────────┐
│  Client (Stream)    │
└─────────────────────┘
         │
         │ POST /api/ingest (multipart: username, frame_id, file)
         ↓
┌─────────────────────────────────────────┐
│  /api/ingest Endpoint                   │
│  - Read frame bytes                     │
│  - Store in frame_store                 │
│  - Enqueue frame (drop oldest if full)  │
│  - Return immediately (<10ms)           │
│  ✓ Now fully async, non-blocking        │
└─────────────────────────────────────────┘
         │
         │ queue.enqueue(QueuedFrame)
         ↓
┌─────────────────────────────────────────┐
│  FrameQueue (AsyncQueue)                │
│  - Bounded size: 10 frames              │
│  - Drop oldest if full                  │
│  - Metrics: enqueued, dequeued, dropped │
│  ✓ Decouples ingestion from processing  │
└─────────────────────────────────────────┘
         │
         │ worker pulls frames
         ↓
┌─────────────────────────────────────────┐
│  VLM Worker Task (background)           │
│  - Pulls from queue                     │
│  - Creates metrics object               │
│  - Calls state machine                  │
│  ✓ Dedicated processing task            │
└─────────────────────────────────────────┘
         │
         │ machine.ingest_frame(username, frame_id)
         ↓
┌─────────────────────────────────────────┐
│  State Machine                          │
│  - Check inflight (2500ms timeout)      │
│  - Dispatch if not inflight             │
│  - Buffer if inflight                   │
│  ✓ Longer timeout prevents false alarms │
└─────────────────────────────────────────┘
         │
         │ post_to_vlm_sync() → async task
         ↓
┌─────────────────────────────────────────┐
│  post_to_vlm_callback()                 │
│  - Get frame from store                 │
│  - Optimize image (resize/compress)     │
│  - Update metrics (http_start)          │
│  - Call post_to_vlm_multipart()         │
│  ✓ Image optimization added             │
└─────────────────────────────────────────┘
         │
         │ await post_to_vlm_multipart()
         ↓
┌──────────────────────────────────────────────────┐
│  post_to_vlm_multipart()                         │
│  - Get singleton httpx client                    │
│  - Use persistent connection                     │
│  - Timeout: 2.5s (aligned with state machine)    │
│  - Update metrics (http_response)                │
│  ✓ Connection pooling eliminates overhead        │
└──────────────────────────────────────────────────┘
         │
         │ HTTP POST (reused connection, no SSL/TCP overhead)
         ↓
┌─────────────────────┐
│   VLM Service       │
│   - Process image   │
│   - Return decision │
└─────────────────────┘
         │
         │ Response (with X-Processing-Time header)
         ↓
┌─────────────────────────────────────────┐
│  Response Processing                    │
│  - Parse decision                       │
│  - Extract server_proc_ms from headers  │
│  - Call machine.vlm_decision()          │
│  - Log detailed metrics                 │
│  ✓ Complete timing breakdown            │
└─────────────────────────────────────────┘
         │
         │ machine.vlm_decision(username, frame_id, decision)
         ↓
┌─────────────────────────────────────────┐
│  State Machine Decision Handling        │
│  - Update YES counter                   │
│  - Clear inflight                       │
│  - Progress step if needed              │
│  - Dispatch buffered frame if exists    │
│  ✓ Proper inflight management           │
└─────────────────────────────────────────┘
```

### Data Flow

**Frame Ingestion Flow**:
```
Client → API Ingest → Queue (enqueue) → Return OK (<10ms)
                        ↓
                   Worker pulls
                        ↓
                State Machine → VLM Processing
```

**Timing Flow**:
```
t0: enqueue_time
t1: dequeue_time  → queue_wait_ms = t1 - t0
t2: http_start_time
t3: http_response_time → http_post_ms = t3 - t2
t4: server_proc_ms (from VLM response header)

Total = queue_wait_ms + http_post_ms
```

---

## Implementation Plan

### Phase 1: Foundation (Critical Path) - Week 1

#### Task 1.1: Create Singleton httpx Client
**Priority**: P0 (Highest impact)  
**Estimated Time**: 4 hours  
**Files**: 
- [`app/core/vlm_client.py`](app/core/vlm_client.py)
- [`app/main.py`](app/main.py)
- [`app/config.py`](app/config.py)

**Changes**:
1. Add configuration in [`app/config.py`](app/config.py):
   ```python
   VLM_HTTP_TIMEOUT_S: float = 2.5
   VLM_MAX_CONNECTIONS: int = 20
   VLM_MAX_KEEPALIVE: int = 10
   ```

2. Add to [`app/core/vlm_client.py`](app/core/vlm_client.py):
   ```python
   _global_client: Optional[httpx.AsyncClient] = None
   
   async def get_vlm_client() -> httpx.AsyncClient
   async def close_vlm_client() -> None
   ```

3. Modify [`post_to_vlm_multipart()`](app/core/vlm_client.py:58):
   - Remove `async with httpx.AsyncClient(...)` context manager
   - Call `client = await get_vlm_client()`
   - Use client directly (no auto-close)

4. Update [`app/main.py`](app/main.py:150-169):
   ```python
   @app.on_event("startup")
   async def startup_event():
       # ... existing ...
       await get_vlm_client()  # Initialize singleton
   
   @app.on_event("shutdown")
   async def shutdown_event():
       # ... existing ...
       await close_vlm_client()  # Clean up
   ```

**Testing**:
- Verify connection reuse with logging
- Measure latency before/after
- Test error handling (connection loss, timeout)
- Monitor connection pool stats

---

#### Task 1.2: Adjust Timeouts
**Priority**: P0 (Blocks false timeouts)  
**Estimated Time**: 2 hours  
**Files**:
- [`app/config.py`](app/config.py)
- [`app/core/statemachine.py`](app/core/statemachine.py:413)
- [`app/core/vlm_client.py`](app/core/vlm_client.py:58)

**Changes**:
1. Add to [`app/config.py`](app/config.py):
   ```python
   VLM_REQUEST_TIMEOUT_MS: int = 2500
   ```

2. Update [`statemachine.py:413`](app/core/statemachine.py:413):
   ```python
   from app.config import settings
   # Line 413:
   if elapsed_ms > settings.VLM_REQUEST_TIMEOUT_MS:  # Was: > 1000
   ```

3. Update [`vlm_client.py:58`](app/core/vlm_client.py:58):
   ```python
   timeout=httpx.Timeout(settings.VLM_HTTP_TIMEOUT_S, connect=5.0)
   ```

4. Improve inflight management in [`statemachine.py`](app/core/statemachine.py):
   - Keep inflight_frame_id set for deduplication
   - Add more logging around timeout events
   - Document timeout behavior

**Testing**:
- Monitor timeout logs
- Verify no false timeouts
- Test with intentionally slow VLM
- Confirm proper error handling

---

### Phase 2: Queue Architecture - Week 1-2

#### Task 2.1: Create Frame Queue System
**Priority**: P1 (High value)  
**Estimated Time**: 6 hours  
**Files**:
- `app/core/frame_queue.py` (NEW)
- [`app/main.py`](app/main.py)
- [`app/config.py`](app/config.py)

**Changes**:
1. Create `app/core/frame_queue.py`:
   - Implement `QueuedFrame` dataclass
   - Implement `FrameQueue` class
   - Add drop-oldest-on-full logic
   - Include statistics tracking

2. Add to [`app/config.py`](app/config.py):
   ```python
   FRAME_QUEUE_SIZE: int = 10
   ```

3. Update [`app/main.py`](app/main.py):
   ```python
   from app.core.frame_queue import FrameQueue
   
   _frame_queue: Optional[FrameQueue] = None
   
   def get_frame_queue() -> FrameQueue:
       return _frame_queue
   
   @app.on_event("startup")
   async def startup_event():
       global _frame_queue
       _frame_queue = FrameQueue(maxsize=settings.FRAME_QUEUE_SIZE)
   ```

**Testing**:
- Unit tests for queue behavior
- Test drop-oldest logic
- Verify statistics tracking
- Load test with rapid enqueueing

---

#### Task 2.2: Modify Ingest Endpoint
**Priority**: P1  
**Estimated Time**: 3 hours  
**Files**:
- [`app/api/ingest.py`](app/api/ingest.py)

**Changes**:
```python
from app.main import get_frame_queue
from app.core.frame_queue import QueuedFrame
from time import perf_counter

@router.post("/ingest")
async def ingest(...):
    api_start = perf_counter()
    
    # Read and store frame
    frame_bytes = await file.read()
    store_frame(frame_id, frame_bytes)
    
    # Enqueue instead of direct processing
    queue = get_frame_queue()
    queued_frame = QueuedFrame(
        username=username,
        frame_id=frame_id,
        enqueue_time=perf_counter()
    )
    await queue.enqueue(queued_frame)
    
    api_duration = (perf_counter() - api_start) * 1000
    logger.info(f"[INGEST] Frame enqueued - duration={api_duration:.2f}ms")
    
    return {"ok": True, "queued": True, "frame_id": frame_id}
```

**Testing**:
- Measure API response time (should be <10ms)
- Verify frames are queued correctly
- Test queue full scenario
- Monitor drop rate

---

#### Task 2.3: Create VLM Worker Task
**Priority**: P1  
**Estimated Time**: 4 hours  
**Files**:
- [`app/main.py`](app/main.py)

**Changes**:
```python
async def vlm_worker_task():
    """Background task that processes frames from queue."""
    from app.api.procedure import machine
    from app.core.frame_queue import FrameQueue
    from time import perf_counter
    
    logger.info("VLM worker task started")
    queue = get_frame_queue()
    
    while True:
        try:
            # Dequeue with timeout
            frame = await queue.dequeue(timeout=1.0)
            
            if frame:
                dequeue_time = perf_counter()
                queue_wait = (dequeue_time - frame.enqueue_time) * 1000
                logger.info(f"[WORKER] Processing frame - frame_id={frame.frame_id}, queue_wait={queue_wait:.2f}ms")
                
                # Process through state machine (existing flow)
                machine.ingest_frame(frame.username, frame.frame_id)
                
        except Exception as e:
            logger.error(f"[WORKER] Error processing frame: {str(e)}", exc_info=True)
            await asyncio.sleep(0.1)

# In startup_event:
_worker_task = None

@app.on_event("startup")
async def startup_event():
    global _worker_task
    # ... existing ...
    _worker_task = asyncio.create_task(vlm_worker_task())
    logger.info("VLM worker task started")

@app.on_event("shutdown")
async def shutdown_event():
    global _worker_task
    # ... existing ...
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            logger.info("VLM worker task cancelled")
```

**Testing**:
- Verify worker processes frames
- Test error handling and recovery
- Monitor queue depth
- Test graceful shutdown

---

### Phase 3: Metrics and Optimization - Week 2

#### Task 3.1: Implement Detailed Metrics
**Priority**: P2 (Important for monitoring)  
**Estimated Time**: 5 hours  
**Files**:
- `app/core/metrics.py` (NEW)
- [`app/core/vlm_client.py`](app/core/vlm_client.py)
- [`app/core/callbacks.py`](app/core/callbacks.py)
- [`app/main.py`](app/main.py) (worker task)

**Changes**:
1. Create `app/core/metrics.py` with `VLMRequestMetrics` class (as designed above)

2. Thread metrics through pipeline:
   - Create in worker task when dequeuing
   - Pass to state machine (optional parameter)
   - Pass to callbacks
   - Update in vlm_client
   - Log in callback after completion

3. Extract VLM processing time from response headers (if available)

**Testing**:
- Verify all timestamps captured
- Test metric calculations
- Review log output for clarity
- Test with missing timestamps

---

#### Task 3.2: Stream Quality Filter Metrics
**Priority**: P2  
**Estimated Time**: 3 hours  
**Files**:
- [`app/services/stream_quality_filter.py`](app/services/stream_quality_filter.py)

**Changes**:
1. Add queue_wait tracking (if queue is added to stream filter)
2. Add http_post_ms timing (already exists, enhance)
3. Add server_proc_ms extraction from response
4. Update logging in `_log_stats()` method

**Testing**:
- Verify stream filter metrics
- Compare with main pipeline metrics
- Test timing accuracy

---

#### Task 3.3: Image Optimization
**Priority**: P3 (Can be deferred)  
**Estimated Time**: 6 hours  
**Files**:
- `app/core/image_optimizer.py` (NEW)
- [`app/config.py`](app/config.py)
- [`app/core/callbacks.py`](app/core/callbacks.py)

**Pre-Implementation Investigation** (2 hours):
- Test different sizes with VLM
- Measure accuracy impact
- Determine optimal dimensions
- Document findings

**Implementation** (4 hours):
1. Create image optimizer module
2. Add configuration settings
3. Integrate in callback before VLM submission
4. Add size comparison logging
5. Make it optional via config flag

**Testing**:
- A/B test with/without optimization
- Measure latency improvement
- Verify accuracy maintained
- Test with various image sizes

---

### Phase 4: Testing and Validation - Week 2-3

#### Task 4.1: Integration Testing
**Estimated Time**: 8 hours

**Test Cases**:
1. End-to-end frame processing
2. Multiple concurrent users
3. Queue full scenarios
4. Timeout scenarios
5. Connection failure recovery
6. Graceful shutdown

**Tools**:
- Unit tests (pytest)
- Integration tests
- Load testing (locust or similar)
- Manual testing

---

#### Task 4.2: Performance Validation
**Estimated Time**: 4 hours

**Metrics to Validate**:
- Throughput (frames/sec)
- API latency
- VLM processing latency
- Queue depths
- Drop rates
- Connection reuse
- Resource usage (CPU, memory, connections)

**Comparison**:
- Before vs after optimization
- Validate expected improvements
- Document actual gains

---

#### Task 4.3: Documentation
**Estimated Time**: 4 hours

**Documents to Update**:
- [`README.md`](README.md) - Add performance section
- [`QUICK_START.md`](QUICK_START.md) - Update if needed
- Create `CONFIGURATION.md` - Document new settings
- Create `TROUBLESHOOTING.md` - Common issues
- Update inline code comments

---

## Risks and Mitigations

### Risk 1: Connection Pool Exhaustion

**Risk**: Singleton client might become a bottleneck  
**Likelihood**: Low  
**Impact**: Medium  

**Mitigation**:
- Configure appropriate connection limits (max_connections=20)
- Monitor connection usage metrics
- Add alerts for pool exhaustion
- Can increase limits if needed
- Consider multiple clients for different services if needed

**Monitoring**:
```python
logger.info(f"Connection pool stats: {client._pool.get_connection_info()}")
```

**Fallback**: Revert to per-request clients if issues arise

---

### Risk 2: Queue Overflow

**Risk**: Queue might drop too many frames  
**Likelihood**: Medium (under high load)  
**Impact**: Low (by design)  

**Mitigation**:
- Monitor drop rate in metrics
- Alert if drop rate > 20%
- Tune queue size via config
- Consider adaptive queue sizing
- Document expected behavior

**Monitoring**:
```python
drop_rate = stats['dropped'] / stats['enqueued'] * 100
if drop_rate > 20:
    logger.warning(f"High drop rate: {drop_rate:.1f}%")
```

**Fallback**: Increase queue size if needed

---

### Risk 3: Timeout Misconfiguration

**Risk**: New timeouts might still be too short/long  
**Likelihood**: Low  
**Impact**: Medium  

**Mitigation**:
- Make timeouts configurable
- Monitor actual processing times
- Adjust based on real-world data
- Document timeout rationale
- Provide tuning guide

**Monitoring**:
- Track VLM response times
- Alert on consistent timeouts
- Analyze timeout patterns

**Fallback**: Revert to previous timeouts if issues

---

### Risk 4: Image Optimization Accuracy Loss

**Risk**: Smaller images might reduce VLM accuracy  
**Likelihood**: Medium  
**Impact**: High  

**Mitigation**:
- Thorough testing before deployment
- A/B testing in production
- Make optimization optional (config flag)
- Document accuracy vs performance tradeoff
- Allow per-user configuration

**Testing**:
- Test with various image sizes
- Measure accuracy metrics
- User acceptance testing
- Rollback capability

**Fallback**: Disable optimization if accuracy drops

---

### Risk 5: Worker Task Failure

**Risk**: Background worker might crash and stop processing  
**Likelihood**: Low  
**Impact**: High  

**Mitigation**:
- Robust error handling in worker
- Auto-restart on failure
- Health check monitoring
- Alert on worker death
- Graceful degradation

**Implementation**:
```python
async def vlm_worker_task():
    while True:
        try:
            # Process frames
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            await asyncio.sleep(1)  # Prevent tight loop
            # Continue processing
```

**Monitoring**:
- Track worker health
- Alert on no processing activity
- Monitor queue backlog

---

### Risk 6: Breaking Changes

**Risk**: Optimizations might break existing functionality  
**Likelihood**: Medium  
**Impact**: High  

**Mitigation**:
- Comprehensive testing before deployment
- Feature flags for new functionality
- Staged rollout (dev → staging → prod)
- Easy rollback mechanism
- Backup of current implementation

**Rollback Plan**:
1. Keep current implementation tagged
2. Document rollback procedure
3. Have rollback tested and ready
4. Monitor closely after deployment

---

## Success Metrics

### Primary Metrics

#### 1. Throughput
- **Current**: ~1 frame per 1.5-2 seconds (0.5-0.67 fps)
- **Target**: 2-3 frames per second (2-3 fps)
- **Measurement**: frames_processed / elapsed_time

#### 2. API Latency
- **Current**: 50-100ms
- **Target**: <10ms (90% reduction)
- **Measurement**: API endpoint response time

#### 3. VLM Processing Latency
- **Current**: 1500-2500ms (with connection overhead)
- **Target**: 600-900ms (eliminate 1s overhead)
- **Measurement**: Total time from dispatch to response

#### 4. Connection Overhead
- **Current**: ~1000ms per request
- **Target**: <100ms for subsequent requests (90% reduction)
- **Measurement**: Time to establish connection

#### 5. False Timeout Rate
- **Current**: ~30-40% of requests timeout
- **Target**: <5% timeout rate
- **Measurement**: timeouts / total_requests

---

### Secondary Metrics

#### 6. Queue Drop Rate
- **Target**: <10% under normal load
- **Alert**: >20% drop rate
- **Measurement**: dropped_frames / enqueued_frames

#### 7. Queue Depth
- **Target**: Average <5 frames
- **Alert**: Consistently at max (10)
- **Measurement**: Average queue size over time

#### 8. Resource Usage
- **CPU**: Should not increase significantly
- **Memory**: Slight increase for queue (~10MB)
- **Connections**: Monitor pool usage
- **Measurement**: System metrics

#### 9. Image Size Reduction
- **Target**: 50-75% size reduction
- **Measurement**: original_bytes / optimized_bytes

#### 10. End-to-End Latency
- **Current**: 1500-2500ms
- **Target**: 600-900ms (60% reduction)
- **Measurement**: enqueue to decision

---

### Monitoring Dashboard

**Key Metrics to Display**:
1. Real-time throughput (fps)
2. API latency (p50, p95, p99)
3. VLM latency breakdown:
   - queue_wait_ms
   - http_post_ms
   - server_proc_ms
4. Queue statistics:
   - Current depth
   - Enqueued rate
   - Dequeued rate
   - Drop rate
5. Connection pool stats:
   - Active connections
   - Idle connections
   - Pool exhaustion events
6. Timeout statistics:
   - Timeout rate
   - Average processing time
7. Image optimization stats:
   - Size reduction
   - Processing time

---

## Conclusion

This architecture provides a comprehensive plan to achieve 2-3x throughput improvement in the VLM-based state machine application. The optimizations are prioritized by impact, with connection pooling and timeout adjustments as the critical path (Phase 1), followed by queue architecture (Phase 2), and metrics/image optimization (Phase 3).

**Key Success Factors**:
1. Implement in phases with testing between each
2. Monitor metrics continuously
3. Be prepared to tune configurations
4. Have rollback plans ready
5. Document everything

**Next Steps**:
1. Review and approve this architecture
2. Set up development environment
3. Begin Phase 1 implementation
4. Establish monitoring/alerting
5. Plan deployment strategy

**Estimated Timeline**:
- **Phase 1 (Critical)**: 2-3 days
- **Phase 2 (High Value)**: 3-4 days
- **Phase 3 (Nice to Have)**: 2-3 days
- **Phase 4 (Testing)**: 3-4 days
- **Total**: 2-3 weeks for complete implementation

---

## Appendix

### A. Configuration Reference

Complete list of new configuration settings:

```python
# app/config.py
class Settings(BaseSettings):
    # Existing settings
    SELF_URL: str
    MENTRA_URL: str
    VLM_URL: str
    RTSP_STREAM_URL: str = ""
    STREAM_USERNAME: str = "stream_user"
    MAX_FRAMES_PER_USER: int = 10
    
    # New performance settings
    VLM_REQUEST_TIMEOUT_MS: int = 2500
    VLM_HTTP_TIMEOUT_S: float = 2.5
    VLM_MAX_CONNECTIONS: int = 20
    VLM_MAX_KEEPALIVE: int = 10
    FRAME_QUEUE_SIZE: int = 10
    
    # Image optimization (optional)
    ENABLE_IMAGE_OPTIMIZATION: bool = False
    VLM_IMAGE_MAX_WIDTH: int = 640
    VLM_IMAGE_MAX_HEIGHT: int = 480
    VLM_IMAGE_QUALITY: int = 85
```

### B. File Changes Summary

**New Files**:
1. `app/core/frame_queue.py` - Frame queue implementation
2. `app/core/metrics.py` - Detailed metrics tracking
3. `app/core/image_optimizer.py` - Image optimization (optional)

**Modified Files**:
1. [`app/config.py`](app/config.py) - Add new configuration settings
2. [`app/main.py`](app/main.py) - Initialize singleton client, queue, worker
3. [`app/api/ingest.py`](app/api/ingest.py) - Enqueue instead of direct call
4. [`app/core/vlm_client.py`](app/core/vlm_client.py) - Singleton client, connection pooling
5. [`app/core/statemachine.py`](app/core/statemachine.py) - Adjust timeout values
6. [`app/core/callbacks.py`](app/core/callbacks.py) - Add metrics, image optimization
7. [`app/services/stream_quality_filter.py`](app/services/stream_quality_filter.py) - Enhanced metrics

### C. Dependencies

No new dependencies required - all using existing packages:
- `httpx` - Already in requirements.txt
- `asyncio` - Python standard library
- `cv2` (OpenCV) - Already in requirements.txt for stream filter

---

**Document End**

For questions or clarifications, please refer to the specific sections above or consult the implementation team.