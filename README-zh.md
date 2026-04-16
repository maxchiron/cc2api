<div align="center">
  <img src="logo.png" alt="cc2api Logo" width="280">
<p align="center"><a href="https://github.com/maxchiron/cc2api">English</a> | <a href="https://github.com/maxchiron/cc2api/blob/main/README-zh.md">中文</a></p>
</div>

<h1>🍤 cc2api</h1>

一个将 Claude Code CLI 暴露为 **Anthropic 兼容 API** 的简易网关。

`cc2api` 接收传入的 `/v1/messages` 请求（Anthropic Messages API 格式），提取 `system prompt` 和 `messages`，使用 bash 调用 `claude -p`，并以标准 Anthropic 格式返回响应——完整支持**流式输出（SSE）**。

## 为什么存在

Claude 官方从 2026.04.04 开始，全面封禁第三方对 cc 的 OAuth 调用，即用 `OAuth generated key + 伪造的 HTTP 请求头` 已经失效。现在必须是经过正版 Claude Code 发出的请求才可以。

我在阅读 `claude --help` 时发现，`claude -p/--print` 参数能够进行快速的一问一答 QA，而不用进入 cc 的交互式 UI。

于是我想，是否可以利用 `claude -p`，将其封装为一个 Anthropic API？于是，本项目由此而生。

本仓库面向希望将现有 Anthropic 风格客户端与 Claude Code 命令行接口对接的开发者。该服务保持 Anthropic 兼容请求形态，同时将实际文本生成委托给 `claude`。

## 关键行为

- 接受 Anthropic Messages API 请求（`/v1/messages`）
- 支持**流式（SSE）**和非流式响应
- 提取 `system` 提示和对话消息
- 使用受控环境变量通过 subprocess 运行 `claude`
- 如果未提供，则使用默认系统提示：`You are a helpful assistant.`
- 可选的 **API Key 鉴权**，通过 `apikeys.txt` 配置，每次请求实时热加载（无需重启服务）

## 支持的端点

### POST `/v1/messages`（主要端点）

接受 Anthropic Messages API 格式的请求体，支持流式和非流式响应。

**非流式示例：**

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 1024,
  "system": "You are a helpful assistant.",
  "messages": [
    {"role": "user", "content": "Translate this into bash: list all Python files recursively."}
  ]
}
```

响应：

```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [{"type": "text", "text": "..."}],
  "model": "claude-sonnet-4-6",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {"input_tokens": 0, "output_tokens": 0}
}
```

**流式示例：**

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 1024,
  "stream": true,
  "messages": [
    {"role": "user", "content": "简单解释量子纠缠。"}
  ]
}
```

响应为标准 Anthropic SSE 事件流（`message_start`、`content_block_delta`、`message_stop` 等）。

### POST `/v1/chat/completions`（OpenAI 兼容，仅供测试）

也提供了一个基础的 OpenAI 兼容端点，仅用于测试目的。**仅支持非流式。**

```json
{
  "model": "claude-code",
  "messages": [
    {"role": "user", "content": "你好！"}
  ]
}
```

> 注意：该端点仅用于快速测试 OpenAI 风格客户端的兼容性，不支持流式输出。

## API Key 鉴权

cc2api 支持可选的 API Key 白名单鉴权。密钥从 `apikeys.txt` 文件中读取，**每次请求都会实时读取**，修改文件后立即生效，无需重启服务器。

### 配置方法

在运行 `cc2api` 的目录下创建 `apikeys.txt`，每行填写一个密钥：

```
sk-mykey-abc123
sk-another-key-xyz
# 以 # 开头的行为注释，会被忽略
```

文件存在且包含至少一个密钥时，所有对 `/v1/messages` 和 `/v1/chat/completions` 的请求都必须在 `Authorization` 请求头中携带有效密钥：

```
Authorization: Bearer sk-mykey-abc123
```

密钥无效或缺失时，返回 `401 Unauthorized`。

当 `apikeys.txt` 不存在或为空时，服务器以**开放模式**运行（不需要鉴权）——与现有配置完全向后兼容。

> **安全提示：** `apikeys.txt` 默认已加入 `.gitignore`，请勿将真实密钥提交到版本控制。

### 带鉴权的请求示例

```bash
curl -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-mykey-abc123" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

## 快速开始

首先，您需要通过 OAuth 登录 claude code cli，这能让后续的 `claude -p` 内部正确运行。

然后，在能够正常使用 `claude -p "你好吗？"` 的机器/终端里，进行本项目的安装：

```bash
git clone https://github.com/maxchiron/cc2api
cd cc2api
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e .
cc2api
```

发送非流式请求到 Anthropic 端点：

```bash
curl -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "解释单一职责原则。"}]
  }'
```

发送流式请求：

```bash
curl -X POST http://127.0.0.1:8080/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "stream": true,
    "messages": [{"role": "user", "content": "解释单一职责原则。"}]
  }'
```

> 如果已配置 `apikeys.txt`，请在每个请求中添加 `-H "Authorization: Bearer <your-key>"`。

## 运行细节

`claude` 的调用使用强制环境变量和 CLI 参数：

- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- `ENABLE_CLAUDEAI_MCP_SERVERS=false`
- `--tools ""`
- `--disable-slash-commands`
- `--settings '{"hooks":{},"mcpServers":{}}'`
- `--system-prompt` 来自请求或使用回退默认值
- `--output-format stream-json`（流式）/ `json`（非流式）

`model` 字段通过 `--model` 直接传递给 `claude` CLI。若模型为 `claude-code`，则省略 `--model`，CLI 使用其默认值。

## TODO

- [ ] support tool-use and more official functions. (Now not support the official format of tool-use request, but prompt-based tool-use should be working)

## 许可

本仓库按原样提供，用于集成和原型开发。
