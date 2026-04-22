<script setup lang="ts">
import { useDashboardStore } from '@/stores/dashboard'

const store = useDashboardStore()

function statusLabel(ws: string) {
  switch (ws) {
    case 'connected': return '已连接'
    case 'reconnecting': return '重连中...'
    default: return '未连接'
  }
}
</script>

<template>
  <header class="h-12 flex items-center justify-between px-4 bg-white/80 dark:bg-gray-900/80 backdrop-blur border-b border-gray-200 dark:border-gray-700 shrink-0">
    <!-- Left: Logo + Title -->
    <div class="flex items-center gap-3">
      <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-hermes-500 to-hermes-700 flex items-center justify-center shadow-sm">
        <svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      </div>
      <span class="font-semibold text-gray-800 dark:text-gray-100 text-sm">Hermes Orchestrator</span>
    </div>

    <!-- Center: Session ID -->
    <div v-if="store.sessionId" class="text-xs text-gray-400 dark:text-gray-500 font-mono">
      Session: {{ store.sessionId.slice(0, 8) }}...
    </div>
    <div v-else class="text-xs text-gray-400" />

    <!-- Right: Connection status + active agents -->
    <div class="flex items-center gap-4">
      <!-- Active agents badge -->
      <div v-if="store.activeAgentCount > 0"
        class="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-agent-green-50 dark:bg-agent-green-900/30 border border-agent-green-200 dark:border-agent-green-800">
        <div class="w-1.5 h-1.5 rounded-full bg-agent-green-500 animate-pulse" />
        <span class="text-xs font-medium text-agent-green-700 dark:text-agent-green-300">
          {{ store.activeAgentCount }} 个 Agent 运行中
        </span>
      </div>

      <!-- WS Status -->
      <div class="flex items-center gap-1.5">
        <div :class="[
          'w-2 h-2 rounded-full transition-colors',
          store.wsStatus === 'connected' ? 'bg-green-500' :
          store.wsStatus === 'reconnecting' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
        ]" />
        <span :class="[
          'text-xs transition-colors',
          store.wsStatus === 'connected' ? 'text-green-600 dark:text-green-400' :
          store.wsStatus === 'reconnecting' ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-500'
        ]">
          {{ statusLabel(store.wsStatus) }}
        </span>
      </div>

      <!-- Dark mode toggle -->
      <button
        @click="$emit('toggle-dark')"
        class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
        title="切换主题"
      >
        <svg class="w-4 h-4 text-gray-500 dark:text-gray-400 hidden dark:block" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
        <svg class="w-4 h-4 text-gray-500 block dark:hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      </button>
    </div>
  </header>
</template>
