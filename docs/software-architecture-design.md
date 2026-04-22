# Hermes-OpenClaw 多智能体协同可视化监控台
# 软件架构设计文档

| 字段 | 内容 |
| :--- | :--- |
| **版本号** | V1.0 |
| **撰写日期** | 2026-04-20 |
| **基于需求** | requirement.md (V1.0) |
| **项目目录** | /home/jister/hermes-openclaw-orchestrator |

---

## 1. 架构设计目标

依据 `requirement.md` 需求文档，本架构需满足以下核心目标：

- **全链路透视**：对"任务输入 → Hermes 分解 → OpenClaw 子 Agent 执行 → 结果汇总"完整链路的可视化
- **实时性 < 100ms**：前端与编排层 WebSocket 连接延迟控制在 100ms 以内
- **DAG 可视化**：基于编排层返回的任务有向无环图，动态渲染节点拓扑
- **流式输出**：子 Agent 回复内容 SSE/WebSocket 流式逐字显示
- **历史回放**：支持历史任务只读模式重现拓扑结构和对话时间轴
- **容错兜底**：编排层服务中断时 3 秒内提示并自动重连，禁止白屏

---

## 2. 技术选型

### 2.1 前端技术栈

| 组件 | 技术选型 | 选型理由 |
| :--- | :--- | :--- |
| **框架** | Vue 3 + TypeScript | 需求文档推荐；与当前 orchestrator_dashboard 现有单文件实现兼容；学习曲线低 |
| **状态管理** | Pinia | Vue 3 官方推荐；比 Vuex 更轻量简洁 |
| **图形可视化** | React Flow 或 AntV G6 | React Flow: 开源活跃、节点/边 API 完善、支持自定义动画；AntV G6: 节点类型丰富、适合复杂 DAG；**推荐 React Flow** |
| **样式/主题** | Tailwind CSS + CSS Variables | 快速实现深色模式切换；原子化 CSS 减少样式冲突 |
| **Markdown 渲染** | marked + highlight.js | 轻量；支持流式增量渲染 |
| **构建工具** | Vite | 与 Vue 3 原生集成；热更新快 |
| **实时通信** | WebSocket (原生) | 与 FastAPI SSE 对接；支持双向通信 |

### 2.2 后端技术栈

| 组件 | 技术选型 | 选型理由 |
| :--- | :--- | :--- |
| **Web 框架** | FastAPI (已有) | ASGI 支持 SSE；自动 OpenAPI 文档 |
| **实时推送** | SSE (sse-starlette, 已有) + WebSocket | SSE 用于服务端→客户端流；WebSocket 用于双向状态同步 |
| **任务状态存储** | 内存 dict (dev) → Redis (prod) | 当前为内存字典；生产环境应迁移至 Redis |
| **进程间通信** | asyncio.Queue | 编排引擎与 SSE 推送队列解耦 |
| **序列化** | Pydantic (已有) | 与 FastAPI 原生集成 |

### 2.3 通信架构

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend (Browser)                  │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐ │
│  │  TaskInput   │  │  Canvas(DAG)  │  │  Drawer     │ │
│  │  Component   │  │  ReactFlow    │  │  Panel      │ │
│  └──────┬───────┘  └───────┬───────┘  └──────┬──────┘ │
│         │                  │                   │        │
│         └──────────────────┴───────────────────┘        │
│                            │                             │
│                    WebSocket + SSE                       │
└────────────────────────────┬────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────┐
│                 FastAPI Backend (Port 8080)              │
│  ┌─────────────────────────────────────────────────┐    │
│  │              EventBus (asyncio.Queue)            │    │
│  │   - task_started  - subtask_started             │    │
│  │   - subtask_completed  - task_completed         │    │
│  │   - agent_thinking  - stream_chunk              │    │
│  └──────────┬──────────────────────────┬───────────┘    │
│             │                          │                 │
│  ┌──────────┴──────────┐   ┌─────────┴──────────┐     │
│  │   SSE Endpoint       │   │  WebSocket Handler │     │
│  │  /api/tasks/{id}/stream│  │  /ws/dashboard      │     │
│  └──────────────────────┘   └────────────────────┘     │
│                                                              │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐   │
│  │  Orchestration│  │ OpenClaw      │  │ AgentRegistry│   │
│  │  Engine       │  │ Connector     │  │              │   │
│  └───────┬──────┘  └───────┬───────┘  └──────┬──────┘   │
└───────────┼─────────────────┼─────────────────┼───────────┘
            │                 │                  │
            │   sessions.create RPC               │
            ▼                 ▼                  │
    ┌───────────────┐  ┌──────────────────────────┐
    │ Hermes Agent   │  │  OpenClaw Gateway :18789  │
    └───────────────┘  │  (WebSocket)              │
                        │  ┌────────────────────┐  │
                        │  │  Sub-Agents        │  │
                        │  │  engineer/         │  │
                        │  │  architect/        │  │
                        │  │  stock-analyst/... │  │
                        │  └────────────────────┘  │
                        └──────────────────────────┘
```

---

## 3. 系统架构设计

### 3.1 整体架构

系统分为五层：

```
┌─────────────────────────────────────────┐
│         Presentation Layer (Frontend)    │
│  Vue 3 + React Flow + Pinia + Tailwind  │
│  - TaskInput      - AgentCanvas         │
│  - DrawerPanel    - HistorySidebar     │
└──────────────────┬──────────────────────┘
                   │ SSE + WebSocket
┌──────────────────┴──────────────────────┐
│          API Gateway Layer (FastAPI)      │
│  - /api/tasks/{id}/stream  (SSE)          │
│  - /ws/dashboard           (WebSocket)   │
│  - /api/orchestrate        (HTTP POST)  │
│  - /api/agents             (HTTP GET)    │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────┴──────────────────────┐
│          Orchestration Engine Layer       │
│  OrchestrationEngine + TaskDecomposer    │
│  + TaskScheduler + EventBus               │
└──────────────────┬──────────────────────┘
                   │ sessions.create RPC
┌──────────────────┴──────────────────────┐
│           Agent Runtime Layer             │
│  OpenClaw Gateway + Hermes + Sub-Agents │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────┴──────────────────────┐
│          Storage Layer (Planned)          │
│  Redis (task state) + File (history)     │
└─────────────────────────────────────────┘
```

### 3.2 模块职责

#### Frontend Modules

| 模块 | 职责 | 文件 |
| :--- | :--- | :--- |
| `TaskInput` | Markdown 编辑器风格输入框 + 模型参数配置栏 + 启动按钮 | `frontend/src/components/TaskInput.vue` |
| `AgentCanvas` | React Flow 画布：渲染 Hermes 节点、OpenClaw 子节点、工具节点、状态动画 | `frontend/src/components/AgentCanvas.vue` |
| `DrawerPanel` | 右侧滑动抽屉：流式对话日志、Markdown 渲染、System Prompt 追溯 | `frontend/src/components/DrawerPanel.vue` |
| `HistorySidebar` | 左侧历史任务列表 + 活跃 Agent 统计 | `frontend/src/components/HistorySidebar.vue` |
| `StatusBar` | 顶部状态栏：会话 ID、连接状态指示灯 | `frontend/src/components/StatusBar.vue` |
| `useDashboard` | Pinia Store：管理所有 Dashboard 状态 | `frontend/src/stores/dashboard.ts` |
| `useWebSocket` | WebSocket 连接管理：自动重连、心跳检测 | `frontend/src/composables/useWebSocket.ts` |

#### Backend Modules

| 模块 | 职责 | 文件 |
| :--- | :--- | :--- |
| `EventBus` | 事件发布订阅中心：解耦编排引擎与 SSE/WebSocket 推送 | `orchestrator/events.py` |
| `OrchestrationEngine` | 任务编排核心：分解、调度、执行、回调 | `orchestrator/engine.py` |
| `TaskDecomposer` | 任务分解器：关键词 → Agent 能力匹配 → SubTask 生成 | `orchestrator/engine.py` |
| `TaskScheduler` | 任务调度器：依赖解析、并行控制 | `orchestrator/engine.py` |
| `OpenClawConnector` | OpenClaw 网关 RPC 客户端 | `agents/openclaw_agent.py` |
| `stream_task_progress` | SSE 端点：消费 EventBus 事件，推送至前端 | `api/main.py` |
| `DashboardWebSocket` | WebSocket 端点：双向实时通道 | `api/websocket.py` |

---

## 4. 核心数据流设计

### 4.1 任务提交流程

```
User Input ("分析北京上海天气并推荐穿衣")
         │
         ▼
POST /api/orchestrate
         │
         ▼
OrchestrationEngine.execute()
  ├─ TaskDecomposer.decompose()
  │    └─ 生成 SubTask DAG:
  │         [weather-beijing] → [weather-shanghai] → [recommend-clothing]
  │           agent: stock-analyst    agent: stock-analyst    agent: architect
  │
  ├─ EventBus.publish("task_started", {task_id, plan})
  │
  ├─ TaskScheduler.schedule()
  │    └─ 并行调度：weather-beijing + weather-shanghai 同时执行
  │
  ├─ OpenClawConnector.execute_subtask() × N
  │    ├─ EventBus.publish("subtask_started", {...})
  │    ├─ EventBus.publish("stream_chunk", {agent_id, chunk})
  │    └─ EventBus.publish("subtask_completed", {...})
  │
  └─ OrchestrationEngine._execute_subtasks()
       └─ EventBus.publish("task_completed", {task_id, results})
```

### 4.2 事件类型定义

所有事件通过 EventBus 分发，SSE 和 WebSocket 消费者订阅：

```python
class DashboardEvent(str, Enum):
    # 任务生命周期
    TASK_STARTED      = "task_started"       # 新任务提交
    TASK_COMPLETED    = "task_completed"     # 任务全部完成
    TASK_FAILED        = "task_failed"        # 任务失败

    # 子任务生命周期
    SUBTASK_STARTED   = "subtask_started"    # 子任务开始
    SUBTASK_COMPLETED = "subtask_completed"   # 子任务完成
    SUBTASK_FAILED    = "subtask_failed"      # 子任务失败

    # 流式输出
    AGENT_THINKING    = "agent_thinking"      # Agent 思考中（呼吸灯）
    STREAM_CHUNK      = "stream_chunk"        # 流式输出片段
    STREAM_DONE       = "stream_done"         # 流式输出结束

    # 连接状态
    HEARTBEAT         = "heartbeat"           # 心跳保活
    CONNECTION_LOST    = "connection_lost"     # 连接断开
    RECONNECTED        = "reconnected"         # 重连成功

@dataclass
class DashboardEventPayload:
    event: DashboardEvent
    task_id: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

### 4.3 DAG 数据结构

前端 React Flow 节点/边数据由后端事件驱动生成：

```typescript
// 节点类型
interface HermesNode {
  id: string;           // "hermes-{task_id}"
  type: 'hermes';
  position: { x: number; y: number };
  data: {
    label: string;
    status: 'idle' | 'running' | 'completed';
    taskId: string;
  };
}

interface AgentNode {
  id: string;           // "agent-{subtask_id}"
  type: 'openclaw';
  data: {
    label: string;      // "stock-analyst"
    agentId: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    isThinking: boolean;
  };
}

interface ToolNode {
  id: string;           // "tool-{tool_name}"
  type: 'tool';
  data: {
    label: string;
    toolName: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
  };
}

// 边（任务流向）
interface FlowEdge {
  id: string;
  source: string;       // 上游节点 ID
  target: string;       // 下游节点 ID
  animated: boolean;    // 是否显示流动动画
  data?: {
    status: 'pending' | 'active' | 'completed';
  };
}
```

---

## 5. API 设计

### 5.1 已有 API（保持兼容）

| 方法 | 路径 | 用途 |
| :--- | :--- | :--- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/info` | 系统信息 |
| `GET` | `/api/agents` | 列出所有注册 Agent |
| `POST` | `/api/orchestrate` | 提交编排任务 |
| `GET` | `/api/tasks/{task_id}` | 查询任务状态 |
| `GET` | `/api/tasks/{task_id}/stream` | SSE 实时进度流 |

### 5.2 新增 API

| 方法 | 路径 | 用途 |
| :--- | :--- | :--- |
| `WS` | `/ws/dashboard` | WebSocket 双向实时通道（替代/补充 SSE） |
| `GET` | `/api/tasks/{task_id}/history` | 获取历史任务（含完整对话日志） |
| `GET` | `/api/tasks/{task_id}/dag` | 获取任务的 DAG 结构（用于画布初始化） |
| `GET` | `/api/agents/{agent_id}/context` | 获取指定 Agent 的最近上下文（用于右侧抽屉追溯） |
| `POST` | `/api/tasks/{task_id}/cancel` | 取消正在执行的任务 |

### 5.3 WebSocket 消息协议

```typescript
// Client → Server
interface WSClientMessage {
  type: 'subscribe' | 'unsubscribe' | 'ping';
  taskId?: string;
}

// Server → Client
interface WSServerMessage {
  event: DashboardEvent;
  taskId: string;
  data: {
    nodeId?: string;
    nodeStatus?: string;
    streamContent?: string;
    dag?: FlowGraph;
    error?: string;
    [key: string]: any;
  };
  timestamp: string;
}
```

---

## 6. 前端架构设计

### 6.1 组件层次

```
App.vue
├── StatusBar.vue          (P0: 连接状态、会话ID)
├── HistorySidebar.vue     (P1: 历史任务列表)
├── MainCanvas.vue
│   ├── AgentCanvas.vue    (P0: React Flow 画布)
│   │   ├── HermesNode.vue
│   │   ├── OpenClawNode.vue
│   │   ├── ToolNode.vue
│   │   └── CustomEdge.vue  (带动画的流动边)
│   └── DrawerPanel.vue    (P0: 右侧流式对话抽屉)
│       ├── ConversationLog.vue
│       └── MarkdownRenderer.vue
└── TaskInputBar.vue       (P0: 底部悬浮输入框)
    ├── MarkdownEditor.vue
    └── ModelConfigBar.vue  (P1: 温度/模型配置)
```

### 6.2 React Flow 节点设计

**Hermes 主控节点**（蓝色，固定顶部中央）：
- 节点形状：圆角矩形 + 图标
- 状态：idle（灰边）→ running（蓝色脉冲）→ completed（绿色）
- 挂载内容：任务描述摘要 + 分解出的子任务数量

**OpenClaw 子节点**（绿色，左/右侧分支）：
- 节点形状：圆角矩形
- 状态：pending（灰）→ running（绿色呼吸灯 + 旋转图标）→ completed（绿色勾）→ failed（红色边框 + 错误图标）
- 挂载内容：Agent 名称 + 当前动作描述

**工具节点**（黄色，叶子节点）：
- 节点形状：菱形 or 六边形
- 状态：同 Agent 节点
- 挂载内容：工具名称 + API 名称

**流动动画边**：
- 虚线 animated 边 + 顺色流动光点（CSS animation）
- 完成时边变为实线 + 绿色

### 6.3 状态管理（Pinia Store）

```typescript
// stores/dashboard.ts
interface DashboardState {
  // 连接
  wsStatus: 'connected' | 'disconnected' | 'reconnecting';
  lastHeartbeat: Date | null;

  // 当前任务
  activeTaskId: string | null;
  activeTaskPlan: SubTask[];

  // DAG 节点 & 边
  nodes: Node[];
  edges: Edge[];

  // 右侧抽屉
  drawerOpen: boolean;
  selectedNodeId: string | null;
  conversationLogs: Map<string, ConversationEntry[]>;

  // 历史
  historyTasks: HistoryTask[];
}

interface ConversationEntry {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  timestamp: Date;
  isStreaming: boolean;
}
```

### 6.4 WebSocket 自动重连策略

```typescript
// composables/useWebSocket.ts
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000]; // 指数退避，最长 8s
const MAX_RECONNECT_ATTEMPTS = 10;

function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => { /* 订阅所有活跃任务 */ };
  ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
  ws.onclose = () => {
    if (attempts < MAX_RECONNECT_ATTEMPTS) {
      setTimeout(connect, RECONNECT_DELAYS[attempts] || 8000);
      store.wsStatus = 'reconnecting';
    } else {
      store.wsStatus = 'disconnected';
    }
  };
}
```

---

## 7. 后端架构设计

### 7.1 EventBus 实现

```python
# orchestrator/events.py
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable

class DashboardEvent(str, Enum):
    TASK_STARTED = "task_started"
    SUBTASK_STARTED = "subtask_started"
    SUBTASK_COMPLETED = "subtask_completed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AGENT_THINKING = "agent_thinking"
    STREAM_CHUNK = "stream_chunk"
    STREAM_DONE = "stream_done"
    HEARTBEAT = "heartbeat"

@dataclass
class DashboardEventPayload:
    event: DashboardEvent
    task_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

class EventBus:
    """Publish-subscribe event bus for dashboard integration."""

    def __init__(self):
        self._subscribers: dict[DashboardEvent, list[Callable[..., Awaitable[None]]]] = {}
        self._queues: dict[DashboardEvent, asyncio.Queue] = {}
        self._global_queue: asyncio.Queue = asyncio.Queue()

    def subscribe(self, event: DashboardEvent, handler: Callable):
        self._subscribers.setdefault(event, []).append(handler)

    def subscriber(self, event: DashboardEvent):
        """Decorator-based subscription."""
        def decorator(fn):
            self.subscribe(event, fn)
            return fn
        return decorator

    async def publish(self, payload: DashboardEventPayload) -> None:
        # Deliver to registered handlers
        for handler in self._subscribers.get(payload.event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception as e:
                logger.warning("event_handler_error", event=payload.event, error=str(e))

        # Put in global queue for SSE consumers
        await self._global_queue.put(payload)

    async def listen(self) -> AsyncGenerator[DashboardEventPayload, None]:
        """Async iterator for SSE endpoint to consume events."""
        while True:
            payload = await self._global_queue.get()
            yield payload
```

### 7.2 编排引擎事件注入

在 `OrchestrationEngine` 初始化时注入 EventBus：

```python
# orchestrator/engine.py
class OrchestrationEngine:
    def __init__(
        self,
        connector: OpenClawConnector,
        registry: AgentRegistry,
        event_bus: EventBus,
        max_parallel: int = 3,
    ):
        self.connector = connector
        self.registry = registry
        self.event_bus = event_bus
        # ...

    async def _run_subtask(self, subtask, agent_info, orchestration_task):
        # Emit: subtask started
        await self.event_bus.publish(DashboardEventPayload(
            event=DashboardEvent.SUBTASK_STARTED,
            task_id=orchestration_task.id,
            data={"subtaskId": subtask.id, "agentId": agent_info.agent_id, "description": subtask.description}
        ))

        # Emit: agent thinking (every 2s while running)
        async def think_heartbeat():
            for _ in range(30):  # max 60s of thinking indicator
                await asyncio.sleep(2)
                await self.event_bus.publish(DashboardEventPayload(
                    event=DashboardEvent.AGENT_THINKING,
                    task_id=orchestration_task.id,
                    data={"subtaskId": subtask.id, "agentId": agent_info.agent_id}
                ))

        think_task = asyncio.create_task(think_heartbeat())

        try:
            result = await self.connector.execute_subtask(agent_info, subtask)
            think_task.cancel()

            # Stream chunks (if result has streaming data)
            if "stream" in result:
                for chunk in result["stream"]:
                    await self.event_bus.publish(DashboardEventPayload(
                        event=DashboardEvent.STREAM_CHUNK,
                        task_id=orchestration_task.id,
                        data={"subtaskId": subtask.id, "agentId": agent_info.agent_id, "chunk": chunk}
                    ))

            await self.event_bus.publish(DashboardEventPayload(
                event=DashboardEvent.SUBTASK_COMPLETED,
                task_id=orchestration_task.id,
                data={"subtaskId": subtask.id, "agentId": agent_info.agent_id, "result": result.get("result")}
            ))
            return result
        except Exception as e:
            think_task.cancel()
            await self.event_bus.publish(DashboardEventPayload(
                event=DashboardEvent.SUBTASK_FAILED,
                task_id=orchestration_task.id,
                data={"subtaskId": subtask.id, "agentId": agent_info.agent_id, "error": str(e)}
            ))
            raise
```

### 7.3 FastAPI 集成

在 `api/main.py` 的 `lifespan` 中初始化 EventBus 并挂载 WebSocket 路由：

```python
# api/main.py (lifespan 部分修改)
from orchestrator.events import EventBus, DashboardEvent, DashboardEventPayload

event_bus = EventBus()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing init code ...

    # Instrument orchestrator engine with event bus
    _engine = OrchestrationEngine(
        connector=_connector,
        registry=_agent_registry,
        max_parallel=3,
        event_bus=event_bus,  # NEW
    )

    # Start SSE broadcaster task
    asyncio.create_task(_broadcast_sse_events(event_bus))

    yield

    await _connector.close()

async def _broadcast_sse_events(event_bus: EventBus):
    """Consume EventBus and push to all SSE/WebSocket clients."""
    async for payload in event_bus.listen():
        message = {
            "event": payload.event.value,
            "data": payload.data,
            "taskId": payload.task_id,
            "timestamp": payload.timestamp.isoformat(),
        }
        # Push to all connected SSE streams (stored in set)
        for queue in _sse_queues:
            await queue.put(message)
        # Push to WebSocket manager
        await ws_manager.broadcast(message)
```

新增 WebSocket 路由：

```python
# api/websocket.py
from fastapi import WebSocket, WebSocketDisconnect
from typing import set

class WSConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, message: dict):
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)

ws_manager = WSConnectionManager()

@router.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
```

---

## 8. 参考架构与设计决策

### 8.1 主要参考项目

| 项目 | Stars | 关键参考点 |
| :--- | ----: | :--- |
| **cft0808/edict** | 15,314 | 三省六部制度化多 Agent 编排；任务状态机（9 状态流转）；Kanban 看板；`flow_log + progress_log` 双通道活动记录；完整归档审计链 |
| **builderz-labs/mission-control** | 4,228 | 自托管 Agent 编排平台；任务分发 + 实时监控 + 成本追踪；TypeScript + React 前端 |
| **proactive-agent/langgraphics** | 94 | LangGraph 实时可视化；Python callback 驱动前端图更新；StateGraph 执行路径高亮 |
| **wickedapp/openclaw-office** | 135 | OpenClaw 虚拟办公室仪表盘；WebSocket 连接 OpenClaw gateway；实时工作流动画 |
| **Coding-Crashkurse/LangGraph-Visualizer** | 19 | FastAPI + WebSocket + React D3 可视化；`APICallbackHandler` 推送节点状态 |

### 8.2 核心设计决策

| 决策点 | 方案 | 备选方案 | 选择理由 |
| :--- | :--- | :--- | :--- |
| **实时推送协议** | SSE（任务进度）+ WebSocket（双向控制）| 纯 WebSocket | SSE 更适合"一对多"服务→浏览器推送；WebSocket 用于用户主动操作（cancel/subscribe） |
| **图可视化库** | React Flow | AntV G6 / D3.js | React Flow 与 Vue 3 可通过 `defineComponent` + Vue wrapper 集成；社区活跃、动画 API 完善 |
| **状态存储** | 内存（dev）+ Redis（prod）| PostgreSQL | 当前编排层已是内存存储；Redis 便于水平扩展多实例 |
| **流式输出** | SSE EventSource | WebSocket 流 | 浏览器原生支持；与 FastAPI SSE 端点天然契合 |
| **前端框架** | Vue 3 | React | 现有单文件实现为 Vue；团队更熟悉；Pinia 状态管理简洁 |
| **DAG 布局** | Dagre 纵向分层布局 | Force-directed | Dagre 自动分层更适合有明确层次的任务流；Force-directed 适合探索性图 |
| **容错机制** | WebSocket 心跳 + 指数退避重连 | 重连 websocket | 参考 openclaw-office；3 次重连失败弹出 UI 提示 |

### 8.3 edict 三省六部架构关键启发

edict 项目（15,314 Stars）是与本项目最相关的 OpenClaw 编排系统，其核心设计理念直接适用于本架构：

1. **状态机驱动**：任务状态严格按定义的状态转移表流转，不允许非法跳转
2. **双通道活动日志**：
   - `flow_log`：任务在 Agent 之间的流转记录（谁→谁+操作类型）
   - `progress_log`：每个 Agent 的实时汇报（tokens/cost/todos/当前动作）
3. **EventBus 解耦**：编排引擎通过事件总线与应用层完全解耦
4. **心跳保活**：Agent 在线状态通过心跳机制实时监测
5. **完全可观测**：每个任务 59 条活动记录，可完整回放整个执行过程

---

## 9. 目录结构设计

```
hermes-openclaw-orchestrator/
├── api/
│   ├── main.py              # FastAPI 入口（修改：集成 EventBus）
│   ├── websocket.py         # NEW: WebSocket 连接管理器
│   └── router.py            # NEW: Dashboard 路由（含 SSE + proxy）
│
├── orchestrator/
│   ├── engine.py            # 修改：EventBus 注入 + 事件发布
│   ├── events.py            # NEW: EventBus（发布-订阅中心）
│   ├── task_scheduler.py    # 已有：调度逻辑
│   └── task_decomposer.py  # 已有：分解逻辑
│
├── agents/
│   ├── openclaw_agent.py    # 已有：OpenClaw RPC 客户端
│   └── cli_executor.py      # 已有：CLI 执行器
│
├── shared/
│   └── types.py             # 已有：共享数据类型
│
├── frontend/                 # NEW: 前端 Vue 3 项目
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── components/
│   │   │   ├── StatusBar.vue
│   │   │   ├── HistorySidebar.vue
│   │   │   ├── MainCanvas.vue
│   │   │   ├── AgentCanvas.vue       # React Flow wrapper
│   │   │   ├── DrawerPanel.vue
│   │   │   ├── TaskInputBar.vue
│   │   │   ├── MarkdownEditor.vue
│   │   │   └── ModelConfigBar.vue
│   │   ├── nodes/                      # React Flow 自定义节点
│   │   │   ├── HermesNode.tsx
│   │   │   ├── OpenClawNode.tsx
│   │   │   ├── ToolNode.tsx
│   │   │   └── CustomEdge.tsx
│   │   ├── stores/
│   │   │   └── dashboard.ts            # Pinia store
│   │   ├── composables/
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useSSE.ts
│   │   │   └── useDagLayout.ts
│   │   └── types/
│   │       └── dashboard.ts
│   └── tailwind.config.js
│
├── docs/
│   └── software-architecture-design.md  # 本文档
│
└── tests/
    └── test_orchestrator_dashboard.py  # NEW: Dashboard 集成测试
```

---

## 10. 实施计划

### 阶段一：后端基础设施（1-2 天）
1. 实现 `orchestrator/events.py` EventBus
2. 在 `OrchestrationEngine` 中注入 EventBus，发布所有事件
3. 实现 `api/websocket.py` WebSocket 连接管理器
4. 新增 SSE `/api/tasks/{id}/stream` 事件推送端点
5. 新增 `/api/tasks/{id}/dag` DAG 结构端点
6. 编写单元测试验证 EventBus

### 阶段二：前端骨架（2-3 天）
1. 初始化 Vue 3 + Vite + TypeScript + Tailwind CSS 项目
2. 集成 React Flow（Vue wrapper）
3. 实现基础布局：StatusBar + HistorySidebar + AgentCanvas + DrawerPanel + TaskInputBar
4. 实现 `useWebSocket` composable（含自动重连）
5. 实现 `useSSE` composable（消费 `/api/tasks/{id}/stream`）

### 阶段三：可视化功能（2-3 天）
1. React Flow 自定义节点：HermesNode、OpenClawNode、ToolNode
2. 自定义边：带流动光点动画的 CustomEdge
3. DAG 布局算法：Dagre 纵向分层
4. 节点状态映射：pending/running/completed/failed → 视觉状态
5. 节点点击事件 → 打开右侧抽屉

### 阶段四：流式输出与对话面板（1-2 天）
1. DrawerPanel 流式内容渲染（Markdown + 逐字显示）
2. SSE STREAM_CHUNK 事件处理
3. System Prompt 片段追溯（从 Agent context 提取）
4. 对话日志 Map（task_id → conversation entries）

### 阶段五：历史回放与完善（1 天）
1. `/api/tasks/{id}/history` 端点
2. HistorySidebar 历史列表
3. 只读模式 DAG 回放
4. 深色模式切换
5. 集成测试

---

## 11. 验收标准映射

| 验收标准 | 对应实现 |
| :--- | :--- |
| 输入任务后画布出现 ≥2 个 OpenClaw 子 Agent 节点 | `TaskDecomposer.decompose()` → 生成 SubTask → DAG 渲染 |
| 右侧面板显示"正在调用天气 API..."时对应节点处于 RUNNING 呼吸状态 | `AGENT_THINKING` 事件 → `isThinking: true` → CSS 呼吸灯动画 |
| 子 Agent 返回 500 错误时节点立即变红并停止后续分发 | `SUBTASK_FAILED` 事件 → 节点红色高亮 + `TaskScheduler` 停止派发 |

---

## 12. 非功能性需求保障

| 需求 | 保障措施 |
| :--- | :--- |
| **NF-01 实时性 < 100ms** | EventBus 内存队列直推 SSE/WebSocket，无额外中间存储；前端 RAF 节流渲染 |
| **NF-02 兼容性 Chrome 120+ / Edge / 深色模式** | CSS Variables 主题变量；Tailwind `dark:` 前缀；Vite dev server HMR |
| **NF-03 错误兜底 3 秒提示重连** | WebSocket `onclose` 指数退避重连（1s/2s/4s/8s）；心跳超时检测；重连失败显示全局 Toast |

---

*文档版本：V1.0 | 基于需求：requirement.md V1.0 | 参考项目：edict, openclaw-office, langgraphics, mission-control*
