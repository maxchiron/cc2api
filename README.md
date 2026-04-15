<h1 align="center">cc2api</h1>

<p align="center">[English](README.md) | [中文](README-zh.md)</p>

<div align="center">
  <img src="logo.png" alt="cc2api Logo">
</div>

A simple gateway that exposes the Claude Code CLI as an OpenAI-compatible API.

`cc2api` accepts incoming `/v1/chat/completions` requests, extracts the `system prompt` and `prompt`, invokes `claude -p` via bash, and returns the cc response in standard OpenAI chat format.

## Why this exists

Starting from April 4, 2026, Claude officially banned third-party OAuth calls to cc, meaning that using `OAuth generated key + forged HTTP headers` is no longer valid. Only requests issued through legitimate claude code are allowed.

While reading `claude --help`, I discovered that the `claude -p/--print` parameter allows for quick Q&A without entering cc's interactive UI.

So I thought, could I utilize `claude -p` to wrap it as an OpenAI API? Thus, this project was born.

This repository is designed for developers who want to bridge existing OpenAI-style clients with the Claude Code command-line interface. The service preserves the request shape expected by OpenAI-compatible tooling while delegating actual text generation to `claude`.


## Key behavior

- Accepts OpenAI-style chat completion requests
- Extracts `system` prompt and conversation messages
- Runs `claude` via subprocess with controlled environment variables
- Uses default system prompt: `You are a helpful assistant.` when none is provided
- Does not support streaming responses

## Supported endpoints

### POST `/v1/chat/completions`

Accepts a request body in OpenAI-compatible chat completion format.

Example:

```json
{
  "model": "claude-code",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Translate this into bash: list all Python files recursively."}
  ]
}
```

The gateway will convert the message list into a single prompt, invoke `claude`, parse its JSON output, and return a response like:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "claude-code",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

## QuickStart

First, you need to log in to claude code cli via OAuth, which allows subsequent `claude -p` to run correctly internally.

Then, on a machine/terminal where you can normally use `claude -p "hello?"`, proceed with the installation of this project:

```bash
git clone https://example.com/your-repo.git cc2api
cd cc2api
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e .
python app.py
```

Then send a request to the OpenAI-compatible endpoint:

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-code","messages":[{"role":"user","content":"Explain the single responsibility principle."}]}'
```

## Runtime details

The `claude` invocation is executed with these enforced environment variables and CLI flags:

- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- `ENABLE_CLAUDEAI_MCP_SERVERS=false`
- `--tools ""`
- `--disable-slash-commands`
- `--settings '{"hooks":{},"mcpServers":{}}'`
- `--system-prompt` set from request or fallback default

If the request includes `model: "claude-code"`, the implementation treats it as the default placeholder and does not pass `--model` explicitly. Any other model value is forwarded to the `claude` CLI.

## TODO

- [ ] streaming response (Now only non-stream)
- [ ] compatible to multi conversations (Now only one round QA)
- [ ] support tool-use and more official functions. (Now not support the official format of tool-use request, but prompt-based tool-use should be working)

## License

This repository is provided as-is for integration and prototyping purposes.
