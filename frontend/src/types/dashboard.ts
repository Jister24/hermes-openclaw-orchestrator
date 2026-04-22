// Dashboard types matching the backend EventBus payload schema

export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed'
export type WsStatus = 'connected' | 'disconnected' | 'reconnecting'
export type NodeType = 'hermes' | 'openclaw' | 'tool'
export type EdgeStatus = 'pending' | 'active' | 'completed' | 'failed'

// Flat node fields matching what Vue Flow stores and components access directly
export interface FlowNode {
  id: string
  type: NodeType
  position: { x: number; y: number }
  // Flat fields accessed by node components directly (no .data nesting)
  label: string
  agentId?: string
  status: NodeStatus
  isThinking?: boolean
  description?: string
  toolName?: string
  taskId?: string
  error?: string
  result?: string
  toolCalls?: string[]
  // Raw data blob (kept for extensibility)
  data: Record<string, unknown>
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  animated?: boolean
  data?: {
    status: EdgeStatus
  }
  style?: Record<string, string>
  markerEnd?: string
}

export interface SubTask {
  id: string
  description: string
  agentType: string
  status: NodeStatus
  priority?: number
  dependsOn?: string[]
  result?: unknown
  error?: string
  startedAt?: string
  completedAt?: string
}

export interface TaskPlan {
  id: string
  description: string
  agent: string
}

export interface ConversationEntry {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  timestamp: Date
  isStreaming: boolean
  agentId?: string
  subtaskId?: string
}

export interface HistoryTask {
  taskId: string
  title: string
  status: NodeStatus
  createdAt: string
  completedAt?: string
  numSubtasks: number
  plan: TaskPlan[]
}

export interface DagPayload {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

// Backend event names
export const DashboardEvents = {
  TASK_STARTED: 'task_started',
  SUBTASK_STARTED: 'subtask_started',
  SUBTASK_COMPLETED: 'subtask_completed',
  SUBTASK_FAILED: 'subtask_failed',
  TASK_COMPLETED: 'task_completed',
  TASK_FAILED: 'task_failed',
  AGENT_THINKING: 'agent_thinking',
  STREAM_CHUNK: 'stream_chunk',
  STREAM_DONE: 'stream_done',
  HEARTBEAT: 'heartbeat',
} as const

export type DashboardEventName = typeof DashboardEvents[keyof typeof DashboardEvents]

export interface WsMessage {
  event: DashboardEventName
  taskId: string
  data: Record<string, unknown>
  timestamp: string
}
