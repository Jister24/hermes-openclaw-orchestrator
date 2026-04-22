<script setup lang="ts">
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'

const store = useDashboardStore()

const collapsed = ref(false)

function formatTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function statusColor(status: string) {
  switch (status) {
    case 'running': return 'text-blue-500 bg-blue-50 dark:bg-blue-900/30 dark:text-blue-300'
    case 'completed': return 'text-green-600 bg-green-50 dark:bg-green-900/30 dark:text-green-300'
    case 'failed': return 'text-red-500 bg-red-50 dark:bg-red-900/30 dark:text-red-300'
    default: return 'text-gray-500 bg-gray-50 dark:bg-gray-800 dark:text-gray-400'
  }
}

const currentTask = computed(() => store.historyTasks.find(t => t.taskId === store.activeTaskId))
</script>

<template>
  <aside :class="[
    'flex flex-col bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 shrink-0 transition-all duration-300',
    collapsed ? 'w-12' : 'w-52'
  ]">
    <!-- Toggle -->
    <button
      @click="collapsed = !collapsed"
      class="flex items-center justify-center h-10 border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
    >
      <svg :class="['w-4 h-4 text-gray-400 transition-transform', collapsed ? 'rotate-180' : '']" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
      </svg>
    </button>

    <!-- Header (only when expanded) -->
    <div v-if="!collapsed" class="px-3 py-2 border-b border-gray-100 dark:border-gray-800">
      <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wider">历史任务</h3>
    </div>

    <!-- Current active task (always visible) -->
    <div v-if="currentTask && !collapsed" class="px-3 py-2 bg-blue-50/50 dark:bg-blue-900/10 border-b border-blue-100 dark:border-blue-900/30">
      <p class="text-xs text-blue-500 font-medium mb-1">当前任务</p>
      <p class="text-xs text-gray-700 dark:text-gray-200 leading-tight line-clamp-2">
        {{ currentTask.title }}
      </p>
      <div class="flex items-center gap-1 mt-1.5">
        <span :class="['text-[10px] px-1.5 py-0.5 rounded-full font-medium', statusColor(store.nodes[0]?.status || 'pending')]">
          {{ currentTask.status === 'running' ? '运行中' : currentTask.status === 'completed' ? '已完成' : currentTask.status === 'failed' ? '失败' : '等待' }}
        </span>
        <span class="text-[10px] text-gray-400">{{ currentTask.numSubtasks }} 个子任务</span>
      </div>
    </div>

    <!-- History list -->
    <div class="flex-1 overflow-y-auto py-1">
      <div v-if="!collapsed && store.historyTasks.length === 0" class="px-3 py-6 text-center">
        <svg class="w-8 h-8 mx-auto text-gray-300 dark:text-gray-600 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
        <p class="text-xs text-gray-400">暂无历史任务</p>
      </div>

      <button
        v-for="task in store.historyTasks"
        :key="task.taskId"
        :class="[
          'w-full text-left px-3 py-2 border-b border-gray-100/50 dark:border-gray-800/50 transition-colors hover:bg-gray-50 dark:hover:bg-gray-800',
          task.taskId === store.activeTaskId ? 'bg-blue-50/50 dark:bg-blue-900/10' : ''
        ]"
        :title="task.title"
      >
        <template v-if="!collapsed">
          <div class="flex items-start gap-1.5">
            <div :class="['w-1.5 h-1.5 rounded-full mt-1 shrink-0', task.status === 'completed' ? 'bg-green-400' : task.status === 'failed' ? 'bg-red-400' : task.status === 'running' ? 'bg-blue-400 animate-pulse' : 'bg-gray-300']" />
            <div class="min-w-0">
              <p class="text-xs text-gray-700 dark:text-gray-200 leading-tight line-clamp-2">{{ task.title }}</p>
              <p class="text-[10px] text-gray-400 mt-0.5">{{ formatTime(task.createdAt) }}</p>
            </div>
          </div>
        </template>
        <template v-else>
          <div :class="['w-2 h-2 rounded-full mx-auto', task.status === 'completed' ? 'bg-green-400' : task.status === 'failed' ? 'bg-red-400' : task.status === 'running' ? 'bg-blue-400' : 'bg-gray-300']" />
        </template>
      </button>
    </div>

    <!-- Agent stats (only when expanded) -->
    <div v-if="!collapsed" class="px-3 py-2 border-t border-gray-200 dark:border-gray-700">
      <p class="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">Agent 统计</p>
      <div class="grid grid-cols-2 gap-1">
        <div class="bg-gray-50 dark:bg-gray-800 rounded-lg p-1.5 text-center">
          <p class="text-sm font-bold text-gray-700 dark:text-gray-200">
            {{ store.historyTasks.filter(t => t.status === 'completed').length }}
          </p>
          <p class="text-[10px] text-gray-400">已完成</p>
        </div>
        <div class="bg-gray-50 dark:bg-gray-800 rounded-lg p-1.5 text-center">
          <p class="text-sm font-bold text-gray-700 dark:text-gray-200">
            {{ store.historyTasks.length }}
          </p>
          <p class="text-[10px] text-gray-400">总任务</p>
        </div>
      </div>
    </div>
  </aside>
</template>
