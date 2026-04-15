import json
import os
import subprocess
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict]
    usage: dict


# ── Claude CLI runner ──────────────────────────────────────────────────────

def run_claude(prompt: str, system_prompt: str, model: Optional[str] = None) -> str:
    env = {
        **os.environ,
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    }

    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
        "--tools", "",
        "--disable-slash-commands",
        "--settings", json.dumps({"hooks": {}, "mcpServers": {}}),
        "--system-prompt", system_prompt,
    ]

    if model:
        cmd.extend(["--model", model])

    cmd.append(prompt)

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