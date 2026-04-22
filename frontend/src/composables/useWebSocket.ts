import { ref, onUnmounted } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { DashboardEvents } from '@/types/dashboard'
import type { WsMessage, TaskPlan } from '@/types/dashboard'

const WS_URL = `ws://localhost:8080/ws/dashboard`
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000]
const MAX_RECONNECT_ATTEMPTS = 10

let ws: WebSocket | null = null
let reconnectAttempts = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let manualClose = false

export function useWebSocket() {
  // NOTE: store must be acquired AFTER Pinia is active — inside the composable
  const isConnected = ref(false)
  const store = useDashboardStore()

  manualClose = false

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return
    }

    try {
      ws = new WebSocket(WS_URL)

      ws.onopen = () => {
        isConnected.value = true
        reconnectAttempts = 0
        store.setWsStatus('connected')
        store.setSessionId(crypto.randomUUID())
        startHeartbeat()
        send({ type: 'subscribe' })
      }

      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data)
          handleMessage(msg)
        } catch (e) {
          console.warn('[WS] Failed to parse message', e)
        }
      }

      ws.onclose = () => {
        isConnected.value = false
        stopHeartbeat()
        if (!manualClose) {
          store.setWsStatus('reconnecting')
          scheduleReconnect()
        } else {
          store.setWsStatus('disconnected')
        }
      }

      ws.onerror = () => {
        // Error is always followed by close
      }
    } catch {
      store.setWsStatus('disconnected')
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      store.setWsStatus('disconnected')
      return
    }
    const delay = RECONNECT_DELAYS[reconnectAttempts] || 8000
    reconnectAttempts++
    reconnectTimer = setTimeout(connect, delay)
  }

  function disconnect() {
    manualClose = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    stopHeartbeat()
    if (ws) {
      ws.close()
      ws = null
    }
    isConnected.value = false
    store.setWsStatus('disconnected')
  }

  function send(data: object) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
    }
  }

  function handleMessage(msg: WsMessage) {
    store.setHeartbeat()
    const d = msg.data as Record<string, string | TaskPlan[] | unknown>

    switch (msg.event) {
      case DashboardEvents.HEARTBEAT:
        break

      case DashboardEvents.TASK_STARTED: {
        const taskId = String(d.taskId ?? '')
        const plan = (d.plan as TaskPlan[]) || []
        store.initDag(taskId, plan)
        store.addHistoryTask({
          taskId,
          title: String(plan[0]?.description ?? '新任务').slice(0, 60),
          status: 'running',
          createdAt: msg.timestamp,
          numSubtasks: plan.length,
          plan,
        })
        break
      }

      case DashboardEvents.SUBTASK_STARTED: {
        const subtaskId = String(d.subtaskId ?? '')
        const agentId = String(d.agentId ?? '')
        const description = String(d.description ?? '')
        store.updateNodeStatus(`agent-${subtaskId}`, 'running')
        store.updateNodeThinking(`agent-${subtaskId}`, true)
        store.updateEdgeStatus(`edge-hermes-${subtaskId}`, 'active')
        store.appendConversationEntry(`agent-${subtaskId}`, {
          role: 'system',
          content: description || `SubTask: ${subtaskId}`,
          timestamp: new Date(),
          isStreaming: false,
          agentId,
          subtaskId,
        })
        break
      }

      case DashboardEvents.SUBTASK_COMPLETED: {
        const subtaskId = String(d.subtaskId ?? '')
        const result = d.result
        store.updateNodeStatus(`agent-${subtaskId}`, 'completed')
        store.updateNodeThinking(`agent-${subtaskId}`, false)
        store.updateEdgeStatus(`edge-hermes-${subtaskId}`, 'completed')
        store.finishStream(subtaskId)
        if (result !== undefined) {
          store.appendConversationEntry(`agent-${subtaskId}`, {
            role: 'assistant',
            content: typeof result === 'string' ? result : JSON.stringify(result),
            timestamp: new Date(),
            isStreaming: false,
          })
        }
        break
      }

      case DashboardEvents.SUBTASK_FAILED: {
        const subtaskId = String(d.subtaskId ?? '')
        const error = String(d.error ?? '')
        store.updateNodeStatus(`agent-${subtaskId}`, 'failed', { error })
        store.updateNodeThinking(`agent-${subtaskId}`, false)
        store.updateEdgeStatus(`edge-hermes-${subtaskId}`, 'failed')
        break
      }

      case DashboardEvents.TASK_COMPLETED: {
        const taskId = String(d.taskId ?? '')
        store.taskCompleted(taskId)
        const hist = store.historyTasks.find(t => t.taskId === taskId)
        if (hist) hist.status = 'completed'
        break
      }

      case DashboardEvents.TASK_FAILED: {
        const taskId = String(d.taskId ?? '')
        const error = String(d.error ?? '')
        store.taskFailed(taskId, error)
        const hist = store.historyTasks.find(t => t.taskId === taskId)
        if (hist) hist.status = 'failed'
        break
      }

      case DashboardEvents.AGENT_THINKING: {
        const subtaskId = String(d.subtaskId ?? '')
        store.updateNodeThinking(`agent-${subtaskId}`, true)
        store.updateEdgeStatus(`edge-hermes-${subtaskId}`, 'active')
        break
      }

      case DashboardEvents.STREAM_CHUNK: {
        const subtaskId = String(d.subtaskId ?? '')
        const chunk = String(d.chunk ?? '')
        const agentId = String(d.agentId ?? '')
        store.addStreamChunk(subtaskId, chunk, agentId)
        break
      }

      case DashboardEvents.STREAM_DONE: {
        const subtaskId = String(d.subtaskId ?? '')
        store.finishStream(subtaskId)
        break
      }
    }
  }

  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      send({ type: 'ping' })
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  connect()

  onUnmounted(() => {
    disconnect()
  })

  return { isConnected, send, connect, disconnect }
}
