<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'

const store = useDashboardStore()
const panelRef = ref<HTMLElement>()

const markedInstance = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    }
  })
)
markedInstance.setOptions({ breaks: true, gfm: true })

const isOpen = computed(() => store.drawerOpen)
const selectedNode = computed(() => store.selectedNode)
const logs = computed(() => store.selectedNodeLogs)

const panelTitle = computed(() => {
  const n = selectedNode.value
  if (!n) return '详情'
  if (n.type === 'hermes') return 'Hermes 主控'
  if (n.type === 'openclaw') return n.label || 'Agent 详情'
  if (n.type === 'tool') return n.label || '工具'
  return '详情'
})

const panelIcon = computed(() => {
  const n = selectedNode.value
  if (!n) return ''
  if (n.type === 'hermes') return 'hermes'
  if (n.type === 'openclaw') return 'agent'
  if (n.type === 'tool') return 'tool'
  return ''
})

function statusBadge(status: string) {
  const map: Record<string, { label: string; cls: string }> = {
    pending: { label: '等待中', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300' },
    running: { label: '运行中', cls: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300 animate-pulse' },
    completed: { label: '已完成', cls: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-300' },
    failed: { label: '失败', cls: 'bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-300' },
  }
  return map[status] || map.pending
}

function formatTime(d: Date) {
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function renderMarkdown(content: string): string {
  try {
    return markedInstance.parse(content) as string
  } catch {
    return content
  }
}

function roleLabel(role: string) {
  const map: Record<string, string> = {
    system: '系统',
    user: '用户',
    assistant: '助手',
    tool: '工具',
  }
  return map[role] || role
}

function roleColor(role: string) {
  const map: Record<string, string> = {
    system: 'bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-300',
    user: 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-300',
    assistant: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-300',
    tool: 'bg-yellow-50 text-yellow-600 dark:bg-yellow-900/20 dark:text-yellow-300',
  }
  return map[role] || ''
}

// Auto-scroll to bottom when logs change
watch(logs, async () => {
  await nextTick()
  if (panelRef.value) {
    panelRef.value.scrollTop = panelRef.value.scrollHeight
  }
}, { deep: true })

function close() {
  store.closeDrawer()
}
</script>

<template>
  <aside
    :class="[
      'h-full flex flex-col bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-700 transition-all duration-300 shrink-0',
      isOpen ? 'w-80' : 'w-0 overflow-hidden'
    ]"
  >
    <!-- Header -->
    <div v-if="isOpen" class="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
      <div class="flex items-center gap-2">
        <!-- Hermes icon -->
        <div v-if="panelIcon === 'hermes'" class="w-7 h-7 rounded-lg bg-hermes-100 dark:bg-hermes-900/30 flex items-center justify-center">
          <svg class="w-4 h-4 text-hermes-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        </div>
        <!-- Agent icon -->
        <div v-else-if="panelIcon === 'agent'" class="w-7 h-7 rounded-lg bg-agent-green-100 dark:bg-agent-green-900/30 flex items-center justify-center">
          <svg class="w-4 h-4 text-agent-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
          </svg>
        </div>
        <!-- Tool icon -->
        <div v-else class="w-7 h-7 rounded-lg bg-tool-100 dark:bg-tool-900/30 flex items-center justify-center">
          <svg class="w-4 h-4 text-tool-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </div>

        <div>
          <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-200">{{ panelTitle }}</h3>
          <p v-if="selectedNode?.agentId" class="text-[10px] text-gray-400">{{ selectedNode.agentId }}</p>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <!-- Status badge -->
        <span v-if="selectedNode" :class="['text-[10px] px-2 py-0.5 rounded-full font-medium', statusBadge(selectedNode.status).cls]">
          {{ statusBadge(selectedNode.status).label }}
        </span>

        <button @click="close" class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
          <svg class="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Node info -->
    <div v-if="isOpen && selectedNode" class="px-4 py-3 border-b border-gray-100 dark:border-gray-800 shrink-0">
      <div v-if="selectedNode.description" class="mb-2">
        <p class="text-[10px] text-gray-400 uppercase tracking-wider mb-1">任务描述</p>
        <p class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">{{ selectedNode.description }}</p>
      </div>
      <div v-if="selectedNode.error" class="mt-2 p-2 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
        <p class="text-[10px] text-red-500 uppercase tracking-wider mb-0.5">错误信息</p>
        <p class="text-xs text-red-600 dark:text-red-300">{{ selectedNode.error }}</p>
      </div>
    </div>

    <!-- Conversation log -->
    <div v-if="isOpen" ref="panelRef" class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
      <div v-if="logs.length === 0" class="flex flex-col items-center justify-center h-full text-center">
        <svg class="w-10 h-10 text-gray-200 dark:text-gray-700 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        <p class="text-xs text-gray-400">暂无对话记录</p>
      </div>

      <div v-for="(entry, i) in logs" :key="i">
        <!-- System entry (single line) -->
        <div v-if="entry.role === 'system'" class="flex items-start gap-2">
          <div class="w-5 h-5 rounded bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center shrink-0 mt-0.5">
            <svg class="w-3 h-3 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <div class="min-w-0">
            <div class="flex items-center gap-1.5 mb-0.5">
              <span class="text-[10px] font-medium text-purple-500">系统</span>
              <span class="text-[10px] text-gray-300 dark:text-gray-600">{{ formatTime(entry.timestamp) }}</span>
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ entry.content }}</p>
          </div>
        </div>

        <!-- Assistant / tool entry (markdown) -->
        <div v-else class="flex items-start gap-2">
          <div :class="['w-5 h-5 rounded flex items-center justify-center shrink-0 mt-0.5 text-[10px] font-bold', roleColor(entry.role)]">
            {{ entry.role === 'assistant' ? 'AI' : entry.role === 'tool' ? 'T' : 'U' }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5 mb-0.5">
              <span :class="['text-[10px] font-medium', entry.role === 'assistant' ? 'text-green-600 dark:text-green-400' : entry.role === 'tool' ? 'text-yellow-600 dark:text-yellow-400' : 'text-blue-600 dark:text-blue-400']">
                {{ roleLabel(entry.role) }}
              </span>
              <span class="text-[10px] text-gray-300 dark:text-gray-600">{{ formatTime(entry.timestamp) }}</span>
              <span v-if="entry.isStreaming" class="text-[10px] text-blue-400 animate-pulse">typing...</span>
            </div>
            <div
              class="text-xs text-gray-700 dark:text-gray-200 leading-relaxed prose prose-xs dark:prose-invert max-w-none prose-pre:bg-gray-100 dark:prose-pre:bg-gray-800 prose-pre:text-gray-700 dark:prose-pre:text-gray-200 prose-code:text-hermes-600 dark:prose-code:text-hermes-300 prose-code:bg-gray-100 dark:prose-code:bg-gray-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none"
              v-html="renderMarkdown(entry.content)"
            />
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>
