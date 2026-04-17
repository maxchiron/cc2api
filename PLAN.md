# Plan: feat/model — Custom Model Name Support

## Context
The server currently hard-codes `"claude-code"` as the only entry in `/v1/models` and uses it as a sentinel meaning "no --model flag". The goal is to expose the three real Anthropic model IDs in `/v1/models` and pass the chosen model to the Claude CLI via `/v1/messages`. Unknown model IDs should return a 400 error. The OpenAI endpoint is out of scope.

## Branch
Create and work on `feat/model`.

## Changes — single file: `/home/wzq/cc2api/app.py`

### 1. Add a model constants list (after the DEFAULT_SYSTEM_PROMPT / apikeys constants, ~line 21)
```python
SUPPORTED_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]
```

### 2. Update model handling in `anthropic_messages()` (line 243)
Current:
```python
model = req.model if req.model != "claude-code" else None
```
Replace with:
```python
if req.model not in SUPPORTED_MODELS:
    raise HTTPException(status_code=400, detail=f"Invalid model id: {req.model!r}")
model = req.model
```
This validates the model name and raises 400 for invalid IDs. All three supported IDs are passed directly to the CLI via `--model`.

### 3. Update `/v1/models` endpoint (lines 274-286)
Replace single `"claude-code"` entry with the three real model IDs:
```python
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": 0, "owned_by": "anthropic"}
            for m in SUPPORTED_MODELS
        ],
    }
```

## Verification
1. `GET /v1/models` → returns 3 entries: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`
2. `POST /v1/messages` with `"model": "claude-sonnet-4-6"` → CLI receives `--model claude-sonnet-4-6`
3. `POST /v1/messages` with `"model": "claude-code"` → returns HTTP 400: `Invalid model id: 'claude-code'`
4. `POST /v1/messages` with unknown model → returns HTTP 400
5. Response `"model"` field echoes back the requested model name (line 267, unchanged)
