<script setup lang="ts">
import { computed } from 'vue'
import type { FlowNode } from '@/types/dashboard'

const props = defineProps<{
  id: string
  data: FlowNode
  selected?: boolean
}>()

const statusConfig = computed(() => {
  const s = props.data.status || 'pending'
  const map: Record<string, { border: string; bg: string; text: string; badge: string }> = {
    pending:   { border: 'border-purple-400', bg: 'bg-purple-50 dark:bg-purple-900/20', text: 'text-purple-500', badge: 'bg-purple-400' },
    running:   { border: 'border-purple-500', bg: 'bg-purple-50 dark:bg-purple-900/20', text: 'text-purple-500', badge: 'bg-purple-500' },
    completed: { border: 'border-green-500', bg: 'bg-green-50 dark:bg-green-900/20', text: 'text-green-500', badge: 'bg-green-500' },
    failed:    { border: 'border-red-500', bg: 'bg-red-50 dark:bg-red-900/20', text: 'text-red-500', badge: 'bg-red-500' },
  }
  return map[s] || map.pending
})
</script>

<template>
  <div
    class="relative flex flex-col w-60 rounded-xl border-2 shadow-lg overflow-visible"
    :class="[statusConfig.border, statusConfig.bg, selected ? 'ring-2 ring-purple-400 ring-offset-2' : '']"
  >
    <!-- Status badge -->
    <div
      class="absolute -top-2.5 -right-2.5 w-5 h-5 rounded-full flex items-center justify-center z-10"
      :class="statusConfig.badge"
    >
      <svg v-if="data.status === 'completed'" class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      <svg v-else-if="data.status === 'failed'" class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      <div v-else-if="data.status === 'running'" class="w-2.5 h-2.5 bg-white/60 rounded-full animate-ping" />
    </div>

    <!-- Agent header -->
    <div class="flex flex-row items-center gap-2 px-3 pt-3 pb-2 w-full">
      <div
        class="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
        :class="data.isThinking ? 'bg-purple-100 dark:bg-purple-900/40' : 'bg-purple-50 dark:bg-purple-900/30'"
      >
        <svg v-if="data.status === 'running' || data.isThinking"
          class="w-5 h-5 text-purple-500 animate-spin" style="animation-duration: 2s"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
        </svg>
        <svg v-else class="w-5 h-5 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
        </svg>
      </div>
      <div class="flex flex-col min-w-0">
        <span class="text-sm font-bold text-gray-700 dark:text-gray-100 truncate">{{ data.label || data.agentId }}</span>
        <span class="text-xs text-gray-400 dark:text-gray-500 truncate">{{ data.agentId }}</span>
      </div>
    </div>

    <!-- Description -->
    <div v-if="data.description" class="px-3 pb-2 w-full">
      <p class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2">{{ data.description }}</p>
    </div>

    <!-- Tool calls -->
    <div v-if="data.toolCalls && data.toolCalls.length > 0" class="px-3 pb-2 w-full">
      <div class="flex flex-wrap gap-1">
        <span
          v-for="tc in (data.toolCalls || []).slice(0, 3)" :key="tc"
          class="text-xs px-1.5 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 truncate max-w-24"
        >{{ tc }}</span>
        <span v-if="(data.toolCalls || []).length > 3"
          class="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-500">
          +{{ data.toolCalls.length - 3 }}
        </span>
      </div>
    </div>

    <!-- Result preview -->
    <div v-if="data.result && data.status === 'completed'" class="px-3 pb-3 w-full">
      <div class="text-xs text-gray-400 dark:text-gray-500 truncate bg-gray-50 dark:bg-gray-800 rounded px-2 py-1">
        {{ String(data.result).slice(0, 60) }}...
      </div>
    </div>

    <!-- Error -->
    <div v-if="data.error" class="px-3 pb-3 w-full">
      <div class="text-xs text-red-500 truncate bg-red-50 dark:bg-red-900/20 rounded px-2 py-1">{{ data.error }}</div>
    </div>

    <!-- Running progress bar -->
    <div v-if="data.status === 'running'" class="w-full h-1 bg-purple-100 dark:bg-purple-900/30 overflow-hidden">
      <div class="h-full bg-purple-400 animate-progress" />
    </div>
  </div>
</template>

<style scoped>
@keyframes progress {
  0% { width: 0%; transform: translateX(0); }
  50% { width: 60%; }
  100% { width: 100%; transform: translateX(150%); }
}
.animate-progress { animation: progress 1.8s ease-in-out infinite; }
.line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
