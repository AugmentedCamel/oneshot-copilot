# VLM Debug Mode Documentation

This document describes how to use the debug mode feature for VLM (Vision Language Model) requests.

## Overview

The debug mode allows you to log detailed information about VLM requests and responses to a file for debugging and analysis purposes. When enabled, the system will capture:

- Timestamp of each request
- Request parameters (question, negative_questions, bounding_questions)
- Raw VLM response JSON
- HTTP timing metrics (request duration, server processing time)
- HTTP status code

## Enabling Debug Mode

There are two ways to enable debug mode:

### 1. Per-Step Configuration (Recommended)

Add a `"debug": true` field to any step in your procedure JSON file:

```json
{
  "id": 1,
  "name": "Example Step",
  "positives": ["Is there a person in the image?"],
  "negatives": ["Is the person wearing a hat?"],
  "bounding_questions": [],
  "timeout_s": 30,
  "debounce": {
    "consecutive_yes": 2
  },
  "debug": true
}
```

### 2. Programmatically

When calling VLM functions directly, pass `debug=True` parameter:

```python
response_json, http_post_ms, server_proc_ms = await post_to_vlm_multipart(
    file_bytes=frame_bytes,
    question=question,
    negatives=negatives,
    vlm_url=settings.VLM_URL,
    bounding_questions=bounding_questions,
    debug=True
)
```

## Debug Log File

Debug information is written to: **`vlm_debug.log`** (in the project root directory)

You can configure the log file path in [`app/config.py`](app/config.py:42):

```python
VLM_DEBUG_LOG_FILE = "vlm_debug.log"  # Change this to customize the path
```

## Log Format

Each debug entry is written in JSON format with clear separation:

```json
{
  "timestamp": "2025-11-04T13:00:00.000000Z",
  "request": {
    "question": "Is there a person in the image?",
    "negative_questions": ["Is the person wearing a hat?"],
    "bounding_questions": []
  },
  "response": {
    "status_code": 200,
    "raw_json": {
      "result": "yes",
      "negative_results": {
        "Is the person wearing a hat?": "no"
      },
      "final": "YES"
    },
    "http_post_ms": 234.56,
    "server_proc_ms": 198.32
  }
}
================================================================================
```

## Provider Support

Debug mode support varies by VLM provider:

| Provider | Debug Support | Notes |
|----------|---------------|-------|
| **Local VLM** | ✅ Full Support | Logs all requests to file |
| **Moondream AI** | ⚠️ Limited | Logs warning; use Moondream dashboard |
| **Auki Local VLM** | ⚠️ Limited | Logs warning; WebSocket provider |

## Example Procedure

See [`app/data/procedures/debug_example.json`](app/data/procedures/debug_example.json) for a complete example:

```json
{
  "id": "debug_example@v1",
  "name": "Debug Example Procedure",
  "version": 1,
  "steps": [
    {
      "id": 1,
      "name": "Step with Debug",
      "positives": ["Is there a person?"],
      "negatives": [],
      "debug": true
    },
    {
      "id": 2,
      "name": "Step without Debug",
      "positives": ["Is there a car?"],
      "negatives": [],
      "debug": false
    }
  ]
}
```

## Testing the Feature

1. Start your VLM service (e.g., local VLM at http://localhost:8899)
2. Load a procedure with debug enabled on a step
3. Send frames to that step
4. Check the `vlm_debug.log` file for detailed entries

## Implementation Details

The debug feature is implemented across multiple files:

1. **[`app/config.py`](app/config.py)** - Configuration for debug log file path
2. **[`app/core/vlm_strategies/base.py`](app/core/vlm_strategies/base.py)** - Base interface with debug parameter
3. **[`app/core/vlm_strategies/local_vlm.py`](app/core/vlm_strategies/local_vlm.py)** - Debug logging implementation
4. **[`app/core/vlm_client.py`](app/core/vlm_client.py)** - Passes debug through to strategies
5. **[`app/core/callbacks.py`](app/core/callbacks.py)** - Extracts debug from step definition
6. **[`app/core/statemachine.py`](app/core/statemachine.py)** - Supports debug field in StepDef

## Troubleshooting

### Debug log file not created

- Ensure the application has write permissions in the project directory
- Check that you're using the Local VLM provider (other providers have limited support)
- Verify the step definition has `"debug": true`

### No entries in debug log

- Confirm that requests are actually reaching the VLM service
- Check application logs for any errors
- Verify the VLM provider is set to "local" in your `.env` file

### Performance concerns

- Debug logging adds minimal overhead (file I/O)
- Only enable debug mode on steps you need to troubleshoot
- The log file will grow over time; rotate or clear it periodically

## Best Practices

1. **Only enable debug on problematic steps** - Don't enable debug globally unless necessary
2. **Monitor log file size** - Clear or rotate the log file periodically
3. **Review logs after issues** - The debug log provides detailed timing and response data
4. **Disable in production** - Remove debug flags from production procedures

## Related Files

- Configuration: [`app/config.py`](app/config.py)
- VLM Strategies: [`app/core/vlm_strategies/`](app/core/vlm_strategies/)
- State Machine: [`app/core/statemachine.py`](app/core/statemachine.py)
- Callbacks: [`app/core/callbacks.py`](app/core/callbacks.py)
- Example Procedure: [`app/data/procedures/debug_example.json`](app/data/procedures/debug_example.json)