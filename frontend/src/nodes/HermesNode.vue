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
  const map: Record<string, { border: string; bg: string; text: string; dot: string }> = {
    pending:    { border: 'border-blue-400', bg: 'bg-blue-50 dark:bg-blue-900/20', text: 'text-blue-500', dot: 'bg-blue-400' },
    running:    { border: 'border-blue-500', bg: 'bg-blue-50 dark:bg-blue-900/20', text: 'text-blue-500', dot: 'bg-blue-500 animate-ping' },
    completed:  { border: 'border-green-500', bg: 'bg-green-50 dark:bg-green-900/20', text: 'text-green-500', dot: 'bg-green-500' },
    failed:     { border: 'border-red-500', bg: 'bg-red-50 dark:bg-red-900/20', text: 'text-red-500', dot: 'bg-red-500' },
  }
  return map[s] || map.pending
})

const statusLabel = computed(() => ({
  pending: '等待中', running: '运行中', completed: '已完成', failed: '失败',
} as Record<string, string>)[props.data.status] || '等待中')
</script>

<template>
  <div
    class="relative flex flex-col items-center justify-center w-56 rounded-xl border-2 shadow-lg"
    :class="[statusConfig.border, statusConfig.bg, selected ? 'ring-2 ring-blue-400 ring-offset-2' : '']"
  >
    <!-- Status dot -->
    <div
      class="absolute -top-2.5 -right-2.5 w-5 h-5 rounded-full flex items-center justify-center"
      :class="statusConfig.dot"
    >
      <svg v-if="data.status === 'completed'" class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      <svg v-else-if="data.status === 'failed'" class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </div>

    <!-- Hermes logo -->
    <div class="w-12 h-12 rounded-full bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center mb-2 mt-1 shadow-md">
      <svg class="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.455 2.456z" />
      </svg>
    </div>

    <span class="text-sm font-bold text-gray-700 dark:text-gray-100">Hermes</span>
    <span class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 max-w-48 text-center truncate px-1">
      {{ data.description || '主任务规划节点' }}
    </span>
    <span class="text-xs mt-1 font-medium" :class="statusConfig.text">{{ statusLabel }}</span>
  </div>
</template>
