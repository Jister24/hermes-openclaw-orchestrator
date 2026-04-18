# Hermes-OpenClaw Orchestrator

Hermes 主 Agent 任务编排层，将复杂任务分解后调度到 OpenClaw 子 Agent 执行。

## 架构

```
┌─────────────────┐      ┌──────────────────────────────────┐
│     Hermes      │      │    Orchestrator (端口 8080)        │
│   (主 Agent)     │─────▶│  • /v1/chat/completions (OpenAI)  │
│                 │      │  • 任务分解                        │
└─────────────────┘      │  • CLI 执行 → OpenClaw 子 Agent   │
                         └──────────────┬───────────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    │  openclaw agent --agent <id> --message  │
                    ▼                                       ▼
           ┌────────────────┐               ┌────────────────┐
           │   architect    │               │ stock-analyst   │
           └────────────────┘               └────────────────┘
```

## 已注册子 Agent

| Agent ID | 名称 | 功能 |
|----------|------|------|
| `architect` | 架构师 | 研究、分析、写作 |
| `engineer` | 工程师 | 代码、文件操作 |
| `stock-analyst` | 股票分析师 | 分析、数学、研究 |

## 快速开始

### 1. 启动 Orchestrator

```bash
cd /home/jister/hermes-openclaw-orchestrator
source venv/bin/activate
python run.py
```

或使用脚本：

```bash
bash start.sh
```

### 2. 注册子 Agent

```bash
curl -s -X POST http://localhost:8080/api/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"architect","name":"架构师","description":"系统架构设计","capabilities":["research","analysis","writing"]}'

curl -s -X POST http://localhost:8080/api/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"engineer","name":"工程师","description":"代码编写","capabilities":["code","file"]}'

curl -s -X POST http://localhost:8080/api/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"stock-analyst","name":"股票分析师","description":"股票分析","capabilities":["analysis","math","research"]}'
```

### 3. 测试任务编排

```bash
curl -s -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"orchestrator","messages":[{"role":"user","content":"帮我分析贵州茅台股票"}]}'
```

### 4. 查询任务状态

```bash
curl http://localhost:8080/api/tasks/<task_id>
```

## 使用方式

### 方式一：在 Hermes 中直接对话（推荐）

在 Hermes chat 中直接描述任务：

```
hermes> 帮我分析贵州茅台的股票
hermes> 帮我写一个 Python Web 服务器
hermes> 研究一下微服务架构的最佳实践
```

Hermes 会自动将任务发送到 Orchestrator，Orchestrator 分解后调用 OpenClaw 子 Agent 执行。

### 方式二：使用 delegate_task 工具

```
hermes> delegate_task(goal="分析A股市场的科技板块趋势")
```

### 方式三：通过 Hermes 的 delegation 配置

如果设置了 `delegation.base_url: http://127.0.0.1:8080/v1`，Hermes 会自动将子任务路由到编排层。

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/v1/chat/completions` | POST | OpenAI 兼容接口，提交任务 |
| `/api/agents` | GET | 列出所有已注册 Agent |
| `/api/agents/register` | POST | 注册新 Agent |
| `/api/tasks/{task_id}` | GET | 查询任务状态 |
| `/api/tasks/{task_id}/stream` | GET | SSE 流式任务进度 |

## 项目结构

```
hermes-openclaw-orchestrator/
├── agents/
│   ├── cli_executor.py      # CLI 执行器
│   └── openclaw_agent.py    # OpenClaw API 客户端
├── api/
│   └── main.py              # FastAPI 主应用
├── orchestrator/
│   └── engine.py            # 任务分解引擎
├── shared/
│   └── types.py             # 数据类型定义
├── run.py                   # 启动脚本
├── start.sh                 # 启动脚本
└── README.md                # 本文档
```

## 配置

- **Orchestrator 地址**: `http://localhost:8080`
- **OpenClaw Gateway**: `http://127.0.0.1:18789`
- **Hermes Gateway**: `http://127.0.0.1:8642`

## 示例输出

```json
{
  "id": "orch-st-01",
  "choices": [{
    "message": {
      "content": "✅ Task decomposed into 1 subtasks.\n\n📋 Execution Plan:\n1. [stock-analyst] 帮我分析贵州茅台股票\n\n📌 Task ID: `orch-st-01`"
    }
  }]
}
```

任务执行结果：

```
Status: completed
Agent: stock-analyst, Status: completed
Response: ## 🍾 贵州茅台 (600519.SH) 深度分析报告

### 一、近期行情
| 项目 | 数值 |
|------|------|
| 收盘价 | ¥1407.24 |
| 今日涨跌 | -3.80% 🔴 |
...
```
