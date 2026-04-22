import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  FlowNode,
  FlowEdge,
  SubTask,
  ConversationEntry,
  HistoryTask,
  TaskPlan,
  WsStatus,
  NodeStatus,
} from '@/types/dashboard'

export const useDashboardStore = defineStore('dashboard', () => {
  // ── Connection state ──────────────────────────────────────
  const wsStatus = ref<WsStatus>('disconnected')
  const lastHeartbeat = ref<Date | null>(null)
  const sessionId = ref<string>('')

  // ── Current active task ────────────────────────────────────
  const activeTaskId = ref<string | null>(null)
  const activeTaskPlan = ref<TaskPlan[]>([])
  const isTaskRunning = ref(false)

  // ── DAG ────────────────────────────────────────────────────
  const nodes = ref<FlowNode[]>([])
  const edges = ref<FlowEdge[]>([])

  // ── Right drawer ───────────────────────────────────────────
  const drawerOpen = ref(false)
  const selectedNodeId = ref<string | null>(null)
  const conversationLogs = ref<Map<string, ConversationEntry[]>>(new Map())

  // ── History ─────────────────────────────────────────────────
  const historyTasks = ref<HistoryTask[]>([])

  // ── Computed ───────────────────────────────────────────────
  const selectedNode = computed(() =>
    nodes.value.find(n => n.id === selectedNodeId.value) || null
  )

  const selectedNodeLogs = computed(() => {
    if (!selectedNodeId.value) return []
    return conversationLogs.value.get(selectedNodeId.value) || []
  })

  const activeAgentCount = computed(() =>
    nodes.value.filter(n => n.type === 'openclaw' && n.data.status === 'running').length
  )

  // ── Actions ─────────────────────────────────────────────────

  function setWsStatus(status: WsStatus) {
    wsStatus.value = status
  }

  function setHeartbeat() {
    lastHeartbeat.value = new Date()
  }

  function setSessionId(id: string) {
    sessionId.value = id
  }

  function initDag(taskId: string, plan: TaskPlan[]) {
    activeTaskId.value = taskId
    activeTaskPlan.value = plan
    isTaskRunning.value = true
    drawerOpen.value = false
    selectedNodeId.value = null
    conversationLogs.value.clear()

    // Create Hermes root node (top center)
    const hermesNode: FlowNode = {
      id: `hermes-${taskId}`,
      type: 'hermes',
      position: { x: 400, y: 50 },
      label: 'Hermes',
      status: 'running',
      taskId,
      description: '任务分解与汇总',
      data: {},
    }

    // Create agent nodes in a row below Hermes
    const centerX = 400
    const startY = 200
    const agentNodes: FlowNode[] = plan.map((p, i) => {
      const offsetX = (i - (plan.length - 1) / 2) * 220
      return {
        id: `agent-${p.id}`,
        type: 'openclaw',
        position: { x: centerX + offsetX - 110, y: startY },
        label: p.agent,
        agentId: p.agent,
        status: 'pending' as NodeStatus,
        isThinking: false,
        description: p.description,
        taskId,
        data: {},
      }
    })

    // Create edges: Hermes → each agent
    const dagEdges: FlowEdge[] = plan.map(p => ({
      id: `edge-hermes-${p.id}`,
      source: `hermes-${taskId}`,
      target: `agent-${p.id}`,
      animated: false,
      data: { status: 'pending' as const },
    }))

    nodes.value = [hermesNode, ...agentNodes]
    edges.value = dagEdges
  }

  function updateNodeStatus(nodeId: string, status: NodeStatus, extra?: Partial<FlowNode>) {
    const node = nodes.value.find(n => n.id === nodeId)
    if (node) {
      node.status = status
      if (extra) {
        Object.assign(node, extra)
      }
    }
  }

  function updateNodeThinking(nodeId: string, isThinking: boolean) {
    const node = nodes.value.find(n => n.id === nodeId)
    if (node) {
      node.isThinking = isThinking
    }
  }

  function updateEdgeStatus(edgeId: string, status: 'pending' | 'active' | 'completed' | 'failed') {
    const edge = edges.value.find(e => e.id === edgeId)
    if (edge) {
      edge.data = { status }
      edge.animated = status === 'active'
    }
  }

  function setSelectedNode(nodeId: string | null) {
    selectedNodeId.value = nodeId
  }

  function setDrawerOpen(open: boolean) {
    drawerOpen.value = open
  }

  function setViewport(_viewport: unknown) {
    // Viewport saved for state restoration
  }

  function addStreamChunk(subtaskId: string, chunk: string, agentId: string) {
    const nodeId = `agent-${subtaskId}`
    const logs = conversationLogs.value.get(nodeId) || []
    // Append to last assistant entry or create new one
    const last = logs[logs.length - 1]
    if (last && last.role === 'assistant' && last.isStreaming) {
      last.content += chunk
    } else {
      logs.push({
        role: 'assistant',
        content: chunk,
        timestamp: new Date(),
        isStreaming: true,
        agentId,
        subtaskId,
      })
    }
    conversationLogs.value.set(nodeId, logs)
  }

  function finishStream(subtaskId: string) {
    const nodeId = `agent-${subtaskId}`
    const logs = conversationLogs.value.get(nodeId) || []
    const last = logs[logs.length - 1]
    if (last && last.isStreaming) {
      last.isStreaming = false
    }
    conversationLogs.value.set(nodeId, logs)
  }

  function appendConversationEntry(nodeId: string, entry: ConversationEntry) {
    const logs = conversationLogs.value.get(nodeId) || []
    logs.push(entry)
    conversationLogs.value.set(nodeId, logs)
  }

  function openDrawerForNode(nodeId: string) {
    selectedNodeId.value = nodeId
    drawerOpen.value = true
  }

  function closeDrawer() {
    drawerOpen.value = false
  }

  function taskCompleted(taskId: string) {
    if (activeTaskId.value === taskId) {
      isTaskRunning.value = false
      // Mark Hermes as completed
      updateNodeStatus(`hermes-${taskId}`, 'completed')
    }
  }

  function taskFailed(taskId: string, error?: string) {
    if (activeTaskId.value === taskId) {
      isTaskRunning.value = false
      updateNodeStatus(`hermes-${taskId}`, 'failed')
      if (error) {
        const hermesNode = nodes.value.find(n => n.id === `hermes-${taskId}`)
        if (hermesNode) hermesNode.data.error = error
      }
    }
  }

  function addHistoryTask(task: HistoryTask) {
    // Avoid duplicates
    const exists = historyTasks.value.find(t => t.taskId === task.taskId)
    if (!exists) {
      historyTasks.value.unshift(task)
      if (historyTasks.value.length > 50) {
        historyTasks.value.pop()
      }
    }
  }

  function clearCurrentTask() {
    activeTaskId.value = null
    activeTaskPlan.value = []
    isTaskRunning.value = false
    nodes.value = []
    edges.value = []
    drawerOpen.value = false
    selectedNodeId.value = null
  }

  return {
    // State
    wsStatus, lastHeartbeat, sessionId,
    activeTaskId, activeTaskPlan, isTaskRunning,
    nodes, edges,
    drawerOpen, selectedNodeId, conversationLogs,
    historyTasks,
    // Computed
    selectedNode, selectedNodeLogs, activeAgentCount,
    // Actions
    setWsStatus, setHeartbeat, setSessionId,
    initDag, updateNodeStatus, updateNodeThinking, updateEdgeStatus,
    addStreamChunk, finishStream, appendConversationEntry,
    openDrawerForNode, closeDrawer,
    taskCompleted, taskFailed, addHistoryTask, clearCurrentTask,
    setSelectedNode, setDrawerOpen, setViewport,
  }
})
