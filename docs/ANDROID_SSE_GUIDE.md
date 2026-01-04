# Android SSE Integration Guide

> Instructions for receiving real-time agent replies in the Oneshot Copilot Android app.

---

## Why SSE?

The Mentra Client (Node.js WebView) receives agent replies via HTTP POST callbacks because it runs a local HTTP server. **Android apps cannot do this** due to:

- Network restrictions (no incoming connections on mobile networks)
- Battery/lifecycle constraints (background server would drain battery)

**Solution:** Server-Sent Events (SSE) - the Android app opens a persistent HTTP connection, and the server pushes events down as they occur.

```
┌─────────────────┐                     ┌─────────────────────┐
│  ANDROID APP    │                     │  COPILOT SERVER     │
│                 │   GET /events/user  │                     │
│  EventSource ◄──┼─────────────────────┼── SSE Manager       │
│       │         │   text/event-stream │        ↑            │
│       ▼         │                     │        │            │
│  Display/TTS    │                     │  AgentService       │
│                 │                     │  (answers questions)│
└─────────────────┘                     └─────────────────────┘
```

---

## What You Need to Implement

### 1. SSE Connection Service

Create a service that:
- Connects to `GET /api/v2/events/{username}` when procedure starts
- Listens for `agent_reply` events
- Displays replies (Toast, overlay, or TTS)
- Handles reconnection on disconnect

### 2. Event Types

| Event | Trigger | Payload | Action |
|-------|---------|---------|--------|
| `agent_reply` | User asked a question via voice | `{"text": "..."}` | Display text or speak via TTS |
| `heartbeat` | Every 30 seconds | `{}` | Ignore (keep-alive) |

---

## Complete Kotlin Implementation

### Dependencies (build.gradle)

```kotlin
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:okhttp-sse:4.12.0")
}
```

### SSEService.kt

```kotlin
package com.example.copilot

import android.util.Log
import okhttp3.*
import okhttp3.sse.*
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Manages SSE connection for receiving real-time agent replies.
 * 
 * Usage:
 *   val sseService = SSEService(baseUrl = "http://copilot:8000")
 *   sseService.connect(username = "my_user") { reply ->
 *       showToast(reply)  // or speakTTS(reply)
 *   }
 *   
 *   // When done:
 *   sseService.disconnect()
 */
class SSEService(
    private val baseUrl: String,
    private val reconnectDelayMs: Long = 3000
) {
    private val TAG = "SSEService"
    
    private var eventSource: EventSource? = null
    private var username: String? = null
    private var onAgentReply: ((String) -> Unit)? = null
    private var shouldReconnect = false
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)  // No read timeout for SSE
        .build()
    
    /**
     * Connect to SSE endpoint and start listening for agent replies.
     * 
     * @param username The user's identifier (same as used for procedures)
     * @param onReply Callback invoked when an agent reply is received
     */
    fun connect(username: String, onReply: (String) -> Unit) {
        this.username = username
        this.onAgentReply = onReply
        this.shouldReconnect = true
        
        startConnection()
    }
    
    /**
     * Disconnect from SSE endpoint.
     */
    fun disconnect() {
        shouldReconnect = false
        eventSource?.cancel()
        eventSource = null
        Log.i(TAG, "Disconnected from SSE")
    }
    
    private fun startConnection() {
        val url = "$baseUrl/api/v2/events/$username"
        Log.i(TAG, "Connecting to SSE: $url")
        
        val request = Request.Builder()
            .url(url)
            .header("Accept", "text/event-stream")
            .build()
        
        val listener = object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                Log.i(TAG, "SSE connected")
            }
            
            override fun onEvent(
                eventSource: EventSource,
                id: String?,
                type: String?,
                data: String
            ) {
                when (type) {
                    "agent_reply" -> {
                        try {
                            val json = JSONObject(data)
                            val text = json.getString("text")
                            Log.i(TAG, "Agent reply: $text")
                            onAgentReply?.invoke(text)
                        } catch (e: Exception) {
                            Log.e(TAG, "Failed to parse agent_reply: $e")
                        }
                    }
                    "heartbeat" -> {
                        Log.d(TAG, "Heartbeat received")
                    }
                }
            }
            
            override fun onClosed(eventSource: EventSource) {
                Log.i(TAG, "SSE closed")
                scheduleReconnect()
            }
            
            override fun onFailure(
                eventSource: EventSource,
                t: Throwable?,
                response: Response?
            ) {
                Log.e(TAG, "SSE failed: ${t?.message}")
                scheduleReconnect()
            }
        }
        
        eventSource = EventSources.createFactory(client)
            .newEventSource(request, listener)
    }
    
    private fun scheduleReconnect() {
        if (!shouldReconnect) return
        
        Log.i(TAG, "Reconnecting in ${reconnectDelayMs}ms...")
        Thread {
            Thread.sleep(reconnectDelayMs)
            if (shouldReconnect) {
                startConnection()
            }
        }.start()
    }
}
```

---

## Integration with Procedure Flow

```kotlin
class ProcedureViewModel : ViewModel() {
    private val sseService = SSEService(baseUrl = CopilotConfig.baseUrl)
    
    fun startProcedure(username: String, procedureId: String) {
        // 1. Start procedure via REST
        copilotApi.startProcedure(username, procedureId)
        
        // 2. Connect SSE for agent replies
        sseService.connect(username) { reply ->
            // Display reply on UI thread
            viewModelScope.launch(Dispatchers.Main) {
                _agentReply.value = reply
                // Or use TTS:
                // textToSpeech.speak(reply, TextToSpeech.QUEUE_FLUSH, null, null)
            }
        }
        
        // 3. Start polling for step progress (existing logic)
        startStatusPolling(username)
    }
    
    fun stopProcedure() {
        sseService.disconnect()
        stopStatusPolling()
    }
    
    override fun onCleared() {
        super.onCleared()
        sseService.disconnect()
    }
}
```

---

## Testing

1. **Start copilot server** with SSE enabled (already done)

2. **Connect from Android** (or curl for testing):
   ```bash
   curl -N http://your-server:8000/api/v2/events/test_user
   ```

3. **Trigger agent reply** (ask a question via Agent Assist):
   ```bash
   curl -X POST http://your-server:8000/api/v2/agent/assist \
     -H "Content-Type: application/json" \
     -d '{"username": "test_user", "query": "How much salt?"}'
   ```

4. **Expected:** SSE connection receives `agent_reply` event instantly.

---

## Checklist

- [ ] Add OkHttp SSE dependency
- [ ] Create `SSEService.kt`
- [ ] Connect SSE when procedure starts
- [ ] Disconnect SSE when procedure ends
- [ ] Handle `agent_reply` events (display or TTS)
- [ ] Handle reconnection on network errors
- [ ] Test with curl before integrating
