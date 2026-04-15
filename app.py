import asyncio
import json
import os
import subprocess
import time
import uuid
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

app = FastAPI(title="cc2api", description="Claude Code CLI to OpenAI-compatible API gateway")

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


# ── Request / Response models (OpenAI-compatible) ──────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "claude-code"
    messages: list[Message]
    max_tokens: Optional[int] = None
    stream: bool = False


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict]
    usage: dict


# ── Claude CLI runner ──────────────────────────────────────────────────────

def run_claude(prompt: str, system_prompt: str, model: Optional[str] = None) -> str:
    cmd = build_claude_cmd(prompt, system_prompt, model, stream=False)
    env = get_claude_env()

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"claude exited with code {result.returncode}: {stderr}")

    return result.stdout


def parse_claude_output(raw: str) -> str:
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return raw.strip()
    except json.JSONDecodeError:
        return raw.strip()


def build_claude_cmd(prompt: str, system_prompt: str, model: Optional[str] = None,
                     stream: bool = False) -> list[str]:
    cmd = [
        "claude",
        "-p",
        "--output-format", "stream-json" if stream else "json",
        "--tools", "",
        "--disable-slash-commands",
        "--settings", json.dumps({"hooks": {}, "mcpServers": {}}),
        "--system-prompt", system_prompt,
    ]
    if stream:
        cmd.extend(["--verbose", "--include-partial-messages"])
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    return cmd


def get_claude_env() -> dict:
    return {
        **os.environ,
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    }


async def stream_claude_sse(prompt: str, system_prompt: str, model: Optional[str],
                            req_model: str) -> AsyncGenerator[str, None]:
    """Run claude with stream-json and yield OpenAI-compatible SSE chunks."""
    cmd = build_claude_cmd(prompt, system_prompt, model, stream=True)
    env = get_claude_env()

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    # First chunk: send the role
    first_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": req_model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"

    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Only care about stream_event with text deltas
            if event.get("type") == "stream_event":
                inner = event.get("event", {})
                etype = inner.get("type")

                if etype == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": req_model,
                            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"

                elif etype == "message_delta":
                    stop_reason = inner.get("delta", {}).get("stop_reason")
                    finish_reason = "stop" if stop_reason else None
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": req_model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

            # Extract usage from the final result event
            elif event.get("type") == "result":
                usage = event.get("usage", {})
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req_model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    },
                }
                yield f"data: {json.dumps(chunk)}\n\n"

        yield "data: [DONE]\n\n"
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    # Extract system prompt and user messages
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

    # Map model name — pass through if not the default placeholder
    model = None if req.model == "claude-code" else req.model

    # ── Streaming response ────────────────────────────────────────────────
    if req.stream:
        return StreamingResponse(
            stream_claude_sse(prompt, system_prompt, model, req.model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Non-streaming response ────────────────────────────────────────────
    try:
        raw = run_claude(prompt, system_prompt, model)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    content = parse_claude_output(raw)

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


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "claude-code",
                "object": "model",
                "created": 0,
                "owned_by": "anthropic",
            }
        ],
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()