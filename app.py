import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

app = FastAPI(
    title="cc2api",
    description="Claude Code CLI to OpenAI-compatible and Anthropic-compatible API gateway",
)

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
APIKEYS_FILE = Path("apikeys.txt")
SUPPORTED_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]
VALID_EFFORT = {"low", "medium", "high", "xhigh", "max"}

_bearer_scheme = HTTPBearer(auto_error=False)


def _load_apikeys() -> set[str]:
    """Read apikeys.txt and return the set of valid keys. Empty set = open access."""
    if not APIKEYS_FILE.exists():
        return set()
    keys = set()
    for line in APIKEYS_FILE.read_text(encoding="utf-8").splitlines():
        key = line.strip()
        if key and not key.startswith("#"):
            keys.add(key)
    return keys


async def verify_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency: enforce API key when apikeys.txt is populated.

    Accepts the key via either:
      - x-api-key: <key>          (Anthropic native format)
      - Authorization: Bearer <key>  (OpenAI / generic Bearer format)
    """
    valid_keys = _load_apikeys()
    if not valid_keys:
        # No keys configured — open access (backwards-compatible).
        return
    # Prefer x-api-key (Anthropic clients), fall back to Bearer token.
    token = request.headers.get("x-api-key") or (
        credentials.credentials if credentials else None
    )
    if not token or token not in valid_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ── OpenAI-compatible models ───────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "claude-code"
    messages: list[Message]
    max_tokens: Optional[int] = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict]
    usage: dict


# ── Anthropic-compatible models ────────────────────────────────────────────

class AnthropicMessage(BaseModel):
    role: str
    content: Union[str, list]


class AnthropicRequest(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024
    messages: list[AnthropicMessage]
    system: Optional[str] = None
    stream: bool = False
    effort: Optional[str] = None


# ── Shared helpers ─────────────────────────────────────────────────────────

def _env() -> dict:
    return {
        **os.environ,
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    }


def _build_cmd(system_prompt: str, model: Optional[str], streaming: bool,
               effort: Optional[str] = None) -> list[str]:
    cmd = [
        "claude",
        "-p",
        "--output-format", "stream-json" if streaming else "json",
        "--tools", "",
        "--disable-slash-commands",
        "--settings", json.dumps({"hooks": {}, "mcpServers": {}}),
        "--system-prompt", system_prompt,
    ]
    if streaming:
        cmd.extend(["--verbose", "--include-partial-messages"])
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])
    return cmd


def _extract_content(content) -> str:
    """Normalise Anthropic content (string or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                parts.append(block.text or "")
        return "".join(parts)
    return str(content)


# ── Sync runner (non-streaming) ────────────────────────────────────────────

def _run_claude(prompt: str, system_prompt: str, model: Optional[str],
                effort: Optional[str] = None) -> str:
    cmd = _build_cmd(system_prompt, model, streaming=False, effort=effort) + [prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, env=_env())
    if result.returncode != 0:
        raise RuntimeError(
            f"claude exited with code {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


def _parse_result(raw: str) -> str:
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return raw.strip()
    except json.JSONDecodeError:
        return raw.strip()


# ── Async streaming runner ─────────────────────────────────────────────────

async def _stream_claude_events(
    prompt: str, system_prompt: str, model: Optional[str],
    effort: Optional[str] = None,
):
    """Yield raw Anthropic-format event dicts from the claude stream-json output."""
    cmd = _build_cmd(system_prompt, model, streaming=True, effort=effort) + [prompt]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env(),
    )
    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        # The CLI wraps each Anthropic streaming event inside {"type":"stream_event","event":{...}}
        if data.get("type") == "stream_event":
            yield data["event"]
    await proc.wait()


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, _: None = Depends(verify_api_key)):
    """OpenAI-compatible chat completions (non-streaming)."""
    system_prompt = DEFAULT_SYSTEM_PROMPT
    user_parts: list[str] = []

    for msg in req.messages:
        if msg.role == "system":
            system_prompt = msg.content
        else:
            user_parts.append(f"{msg.role}: {msg.content}")

    if not user_parts:
        raise HTTPException(status_code=400, detail="No user/assistant messages provided")

    prompt = "\n\n".join(user_parts)
    model = None if req.model == "claude-code" else req.model

    try:
        raw = _run_claude(prompt, system_prompt, model)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    content = _parse_result(raw)

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=req.model,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )


@app.post("/v1/messages")
async def anthropic_messages(req: AnthropicRequest, _: None = Depends(verify_api_key)):
    """Anthropic Messages API endpoint with optional SSE streaming."""
    system_prompt = req.system or DEFAULT_SYSTEM_PROMPT

    parts = []
    for msg in req.messages:
        parts.append(f"{msg.role}: {_extract_content(msg.content)}")
    prompt = "\n\n".join(parts)

    if not prompt.strip():
        raise HTTPException(status_code=400, detail="No messages provided")

    if req.model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model id: {req.model!r}")
    model = req.model

    if req.effort and req.effort not in VALID_EFFORT:
        raise HTTPException(status_code=400,
            detail=f"Invalid effort '{req.effort}'. Must be one of: {sorted(VALID_EFFORT)}")

    # ── Streaming response ─────────────────────────────────────────────────
    if req.stream:
        async def sse_generator():
            async for event in _stream_claude_events(prompt, system_prompt, model, effort=req.effort):
                event_type = event.get("type", "")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    # ── Non-streaming response ─────────────────────────────────────────────
    try:
        raw = _run_claude(prompt, system_prompt, model, effort=req.effort)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    content = _parse_result(raw)

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content}],
        "model": req.model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": 0, "owned_by": "anthropic"}
            for m in SUPPORTED_MODELS
        ],
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
