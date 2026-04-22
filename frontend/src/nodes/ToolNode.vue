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
  const map: Record<string, { border: string; bg: string; text: string }> = {
    pending:   { border: 'border-yellow-300 dark:border-yellow-600', bg: 'bg-yellow-50 dark:bg-yellow-900/20', text: 'text-yellow-400' },
    running:   { border: 'border-yellow-500', bg: 'bg-yellow-50 dark:bg-yellow-900/20', text: 'text-yellow-500' },
    completed: { border: 'border-green-500', bg: 'bg-green-50 dark:bg-green-900/20', text: 'text-green-500' },
    failed:    { border: 'border-red-500', bg: 'bg-red-50 dark:bg-red-900/20', text: 'text-red-500' },
  }
  return map[s] || map.pending
})

const iconType = computed(() => {
  const l = (props.data.toolName || props.data.label || '').toLowerCase()
  if (l.includes('search') || l.includes('web')) return 'search'
  if (l.includes('code') || l.includes('python') || l.includes('shell')) return 'code'
  if (l.includes('write') || l.includes('doc') || l.includes('report')) return 'write'
  if (l.includes('data') || l.includes('stock') || l.includes('chart')) return 'data'
  if (l.includes('terminal') || l.includes('cli')) return 'terminal'
  return 'tool'
})
</script>

<template>
  <div
    class="relative flex flex-col items-center justify-center w-36 h-28 rounded-lg border-2 shadow-md cursor-pointer transition-all duration-300"
    :class="[
      statusConfig.border, statusConfig.bg,
      data.status === 'running' ? 'shadow-lg ring-2 ring-yellow-400/30' : '',
      data.status === 'failed' ? 'ring-2 ring-red-500/50' : '',
      selected ? 'ring-2 ring-offset-2 ring-yellow-400' : '',
    ]"
  >
    <!-- Status dot -->
    <div
      class="absolute -top-2.5 -right-2.5 w-4 h-4 rounded-full flex items-center justify-center z-10"
      :class="{
        'bg-yellow-400': data.status === 'pending',
        'bg-yellow-500': data.status === 'running',
        'bg-green-500': data.status === 'completed',
        'bg-red-500': data.status === 'failed',
      }"
    >
      <svg v-if="data.status === 'completed'" class="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      <div v-else-if="data.status === 'running'" class="w-2 h-2 bg-white/50 rounded-full animate-ping" />
      <svg v-else-if="data.status === 'failed'" class="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </div>

    <!-- Icon -->
    <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-yellow-100 to-orange-100 dark:from-yellow-900/40 dark:to-orange-900/40 flex items-center justify-center mb-1">
      <svg v-if="iconType === 'search'" class="w-5 h-5" :class="statusConfig.text" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <svg v-else-if="iconType === 'code'" class="w-5 h-5" :class="statusConfig.text" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
      </svg>
      <svg v-else-if="iconType === 'write'" class="w-5 h-5" :class="statusConfig.text" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
      <svg v-else-if="iconType === 'data'" class="w-5 h-5" :class="statusConfig.text" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
      <svg v-else-if="iconType === 'terminal'" class="w-5 h-5" :class="statusConfig.text" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
      </svg>
      <svg v-else class="w-5 h-5" :class="statusConfig.text" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    </div>

    <span class="text-xs font-semibold text-gray-700 dark:text-gray-200 text-center leading-tight px-1">{{ data.label }}</span>
    <span class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 max-w-32 text-center truncate px-1">
      {{ data.toolName || data.description || '' }}
    </span>

    <!-- Error tooltip -->
    <div v-if="data.error"
      class="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 bg-red-500 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-50">
      {{ data.error }}
    </div>
  </div>
</template>
