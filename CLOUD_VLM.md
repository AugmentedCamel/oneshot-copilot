# Moondream AI Cloud VLM Integration

## Overview

This system supports both local and Moondream AI cloud-based Vision Language Models.

## Configuration

Set `USE_CLOUD_VLM=true` in [`.env`](.env) to use Moondream AI cloud instead of local VLM.

### Environment Variables

```bash
USE_CLOUD_VLM=false                           # Set to true to enable Moondream AI
MOONDREAM_API_KEY=your_moondream_api_key_here # Get from https://moondream.ai
```

### Getting Your API Key

1. Sign up at [moondream.ai](https://moondream.ai)
2. Navigate to API settings
3. Generate an API key
4. Add to `.env` as `MOONDREAM_API_KEY`

## API Details

- **Base URL**: `https://api.moondream.ai`
- **Endpoint**: `/v1/query`
- **Method**: POST (multipart/form-data)
- **Authentication**: Bearer token in Authorization header
- **Documentation**: https://docs.moondream.ai/api

## Important Limitations

### ⚠️ Negative Questions Not Supported

**Moondream AI cloud does not support negative questions.** When `USE_CLOUD_VLM=true`:
- Only the positive question from `step.positives[0]` is sent
- Any `step.negatives` questions are **ignored**
- A warning is logged when negatives are present but ignored

**Example:**
```json
{
  "steps": [
    {
      "positives": ["Is there a pizza?"],
      "negatives": ["Is there NO pizza?"]  // ← IGNORED in cloud mode
    }
  ]
}
```

### Local vs Moondream AI Behavior

| Feature | Local VLM | Moondream AI Cloud |
|---------|-----------|---------------------|
| Positive questions | ✅ Supported | ✅ Supported |
| Negative questions | ✅ Supported | ❌ **Ignored** |
| Endpoint | `/qa` multipart | `/v1/query` multipart |
| Authentication | None | API key required |
| Response format | JSON decision | Natural language → normalized |

## Response Normalization

Moondream AI returns natural language answers that are normalized to YES/NO/UNCERTAIN:

| Moondream Response | Normalized Decision |
|--------------------|---------------------|
| "Yes, I see a pizza" | YES |
| "No pizza visible" | NO |
| "I'm not sure" | UNCERTAIN |

## Switching Between Local and Cloud

Simply update `.env`:
```bash
USE_CLOUD_VLM=false  # Use local VLM
USE_CLOUD_VLM=true   # Use Moondream AI cloud
```

No code changes or procedure modifications needed. The system automatically routes to the correct VLM implementation.

## Troubleshooting

### Authentication Errors
- Verify `MOONDREAM_API_KEY` is set correctly in `.env`
- Check key hasn't expired at moondream.ai dashboard
- Ensure key has proper permissions

### Response Parsing Issues
- Check logs for `[MOONDREAM]` entries
- Verify question format is clear and answerable
- Review normalized decision logic in [`vlm_client.py`](app/core/vlm_client.py)

## Implementation Details

### Request Format

```python
# Headers
headers = {
    "Authorization": f"Bearer {MOONDREAM_API_KEY}"
}

# Files
files = {
    "image": ("image.jpg", file_bytes, "image/jpeg")
}

# Form data
data = {
    "question": "Is there a pizza?"
}

# POST to https://api.moondream.ai/v1/query
```

### Response Format

```json
{
  "answer": "Yes, there is a pizza visible in the image."
}
```

### Normalization Logic

The [`_normalize_moondream_response()`](app/core/vlm_client.py) function converts natural language responses:

- **Affirmative keywords**: "yes", "correct", "true", "affirmative", "indeed", "visible", "present" → `YES`
- **Negative keywords**: "no", "not", "incorrect", "false", "negative", "absent", "missing" → `NO`
- **Ambiguous responses**: → `UNCERTAIN`

## Logging

Look for these log prefixes to track Moondream AI requests:
- `[MOONDREAM]` - Moondream-specific operations
- `[VLM_CLIENT]` - General VLM client routing
- `[⏱️ TIMING]` - Performance metrics

Example log output:
```
[VLM_CLIENT] Routing to Moondream AI Cloud VLM
[MOONDREAM] Sending request to Moondream AI - url=https://api.moondream.ai
[⏱️ TIMING] Sending HTTP request to Moondream AI
[⏱️ TIMING] Moondream AI response - duration=245.32ms, status=200
[MOONDREAM] Request successful - decision=YES