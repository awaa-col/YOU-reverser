# 🔄 OpenAI API 反向代理服务

## 项目简介

简单来说自己闲着蛋疼,边问Claude边写的代码,目前支持X.ai,Grok.com,you.com
## ✨ 主要特性

- 🔄 **统一接口**：提供与 OpenAI API 兼容的端点，可直接替换 OpenAI 接口使用
- 🌐 **多平台支持**：
  - You.com (Claude 3.5/3.7 Sonnet 等)
  - X.ai (Grok 模型)
  - Grok.com 官方平台
- 🔁 **智能轮换**：自动轮换 Cookie/凭证，最大化 API 使用效率
- ⚡ **流式响应**：支持流式输出（SSE），实时获取 AI 回复
- 🛡️ **防护绕过**：内置 Cloudflare 防护绕过机制
- 🕒 **冷却管理**：智能管理 API 限流，自动冷却和恢复
- 📊 **状态监控**：追踪各平台凭证使用情况和有效性

## 🛠️ 安装与使用

### 安装步骤

1. 克隆或下载本仓库到本地
2. 运行 `安装依赖.bat` 创建虚拟环境并安装所需依赖
3. 首次运行 `Start.bat` 将生成默认配置文件
4. 编辑 `config.json` 添加您的凭证
5. 再次运行 `Start.bat` 启动服务

### 配置说明

首次运行会创建配置文件 `config.json`，需要填写相应平台的凭证：

```json
{
  "you_cookies": ["YOUR_YOU_COOKIE_HERE"],
  "x_credentials": [{
    "cookie": "YOUR_X_COOKIE_HERE",
    "authorization": "YOUR_X_AUTH_HERE",
    "x-csrf-token": "YOUR_X_CSRF_TOKEN_HERE"
  }],
  "grok_cookies": ["YOUR_GROK_COOKIE_HERE"],
  "log_level": "INFO",
  "cookie_management": {
    "you": {
      "rotation_strategy": "round_robin",
      "rotation_interval": 3,
      "cooldown_minutes": 60,
      "validation_interval_hours": 1
    },
    "x": {
      "rotation_strategy": "round_robin",
      "rotation_interval": 3,
      "cooldown_hours": 24
    },
    "grok": {
      "rotation_strategy": "round_robin",
      "rotation_interval": 3,
      "cooldown_minutes": 60
    }
  },
  "you_settings": {
    "custom_message": "",
    "custom_filename": ""
  }
}
```

## 🚀 API 使用示例

服务启动后，默认监听 `0.0.0.0:8080`，提供以下 API 端点：

### 获取可用模型列表

```bash
curl http://localhost:8080/v1/models
```

### 发送聊天请求

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "You.com:claude_3_5_sonnet",
    "messages": [
      {"role": "user", "content": "Hello, how are you today?"}
    ],
    "stream": true
  }'
```

## 🔧 轮换策略配置

支持多种凭证轮换策略：

- `round_robin`：轮流使用每个凭证
- `random`：随机选择凭证
- `least_used`：优先使用请求次数最少的凭证
- `most_remaining`：(仅限 Grok) 优先使用剩余额度最多的凭证

# 我不对任何由于使用本反向代理而导致的账号等情况封禁负责!!!

---
