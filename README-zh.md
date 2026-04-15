<div align="center">
  <img src="logo.png" alt="cc2api Logo" width="280">
<p align="center"><a href="https://github.com/maxchiron/cc2api">English</a> | <a href="https://github.com/maxchiron/cc2api/blob/main/README-zh.md">中文</a></p>
</div>

<h1>🍤 cc2api</h1>

一个将 Claude Code CLI 暴露为 OpenAI 兼容 API 的简易网关。

`cc2api` 接收传入的 `/v1/chat/completions` 请求，提取`system prompt`和`prompt`，使用bash调用 `claude -p`，并将cc的响应以标准 OpenAI 聊天格式返回。

## 为什么存在

Claude官方从2026.0404开始，全面封禁第三方对cc的OAuth调用，即，用`OAuth generated key + 伪造的HTTP请求头`，已经失效。现在必须是经过正版claude code发出的请求才可以。

我在阅读claude --help时发现，claude -p/--print 参数，能够进行快速的一问一答QA，而不用进入cc的交互式UI。

于是我想，是否可以利用claude -p，将其封装为一个OpenAI api？于是，本项目由此而生。

claud本仓库面向希望将现有 OpenAI 风格客户端与 Claude Code 命令行接口对接的开发者。该服务保持 OpenAI 兼容请求形态，同时将实际文本生成委托给 `claude`。

## 关键行为

- 接受 OpenAI 风格的聊天补全请求
- 提取 `system` 提示和对话消息
- 使用受控环境变量通过 subprocess 运行 `claude`
- 如果未提供，则使用默认系统提示：`You are a helpful assistant.`
- 暂不支持流式响应

## 支持的端点

### POST `/v1/chat/completions`

接受 OpenAI 兼容的聊天补全请求体。

示例：

```json
{
  "model": "claude-code",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Translate this into bash: list all Python files recursively."}
  ]
}
```

网关会将消息列表转换为单个提示，调用 `claude`，解析其 JSON 输出，并返回类似以下的响应：

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

## 快速开始

首先，您需要通过OAuth登录claude code cli，这能够让后续的claude -p内部实现正确运行。

然后，在能够正常使用 `claude -p "你好吗？"`的机器/终端里，进行本项目的安装：

```bash
git clone https://example.com/your-repo.git cc2api
cd cc2api
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e .
python app.py
```

然后发送请求到 OpenAI 兼容端点：

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-code","messages":[{"role":"user","content":"Explain the single responsibility principle."}]}'
```

## 运行细节

`claude` 的调用使用强制环境变量和 CLI 参数：

- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- `ENABLE_CLAUDEAI_MCP_SERVERS=false`
- `--tools ""`
- `--disable-slash-commands`
- `--settings '{"hooks":{},"mcpServers":{}}'`
- `--system-prompt` 来自请求或使用回退默认值

如果请求中包含 `model: "claude-code"`，实现会将其视为默认占位符，不会显式传递 `--model`。任何其他模型值都会转发给 `claude` CLI。

## TODO

- [ ] streaming response (Now only non-stream)
- [ ] compatible to multi conversations (Now only one round QA)
- [ ] support tool-use and more official functions. (Now not support the official format of tool-use request, but prompt-based tool-use should be working)

## 许可

本仓库按原样提供，用于集成和原型开发。