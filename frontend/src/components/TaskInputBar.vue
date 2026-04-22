<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'

const store = useDashboardStore()

const taskInput = ref('')
const temperature = ref(0.7)
const model = ref('')
const isSubmitting = ref(false)
const availableModels = ref<string[]>([])
const modelLoading = ref(true)

const canSubmit = computed(() => taskInput.value.trim().length > 0 && !isSubmitting.value && model.value)

// Load available models from backend on mount
onMounted(async () => {
  try {
    // Fetch available models from orchestrator backend
    const resp = await fetch('/api/models')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()

    if (data.models && data.models.length > 0) {
      availableModels.value = data.models
      model.value = data.default || data.models[0]
    } else {
      // Fallback if config read fails
      availableModels.value = ['minimax/MiniMax-M2.7', 'deepseek/deepseek-chat', 'qwen/qwen3.5-plus']
      model.value = availableModels.value[0]
    }
  } catch (e) {
    console.warn('[TaskInput] Failed to load models, using defaults:', e)
    availableModels.value = ['minimax/MiniMax-M2.7', 'deepseek/deepseek-chat', 'qwen/qwen3.5-plus']
    model.value = availableModels.value[0]
  } finally {
    modelLoading.value = false
  }
})

async function submitTask() {
  if (!canSubmit.value) return
  isSubmitting.value = true
  try {
    const resp = await fetch('/api/orchestrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task: taskInput.value.trim(),
        context: {
          temperature: temperature.value,
          model: model.value,
        },
        priority: 1,
      }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    // Store will be updated via WebSocket events
    taskInput.value = ''
  } catch (e) {
    console.error('[TaskInput] Submit failed:', e)
  } finally {
    isSubmitting.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    submitTask()
  }
}
</script>

<template>
  <div class="relative bg-white/90 dark:bg-gray-900/90 backdrop-blur border-t border-gray-200 dark:border-gray-700">
    <!-- Quick config bar (collapsible) -->
    <div class="flex items-center gap-3 px-4 py-2 border-b border-gray-100 dark:border-gray-800">
      <span class="text-xs text-gray-400">Temperature:</span>
      <input
        v-model.number="temperature"
        type="range" min="0" max="1" step="0.1"
        class="w-20 h-1 bg-gray-200 dark:bg-gray-700 rounded-full appearance-none cursor-pointer accent-hermes-500"
      />
      <span class="text-xs text-gray-600 dark:text-gray-300 w-6">{{ temperature.toFixed(1) }}</span>

      <div class="w-px h-4 bg-gray-200 dark:bg-gray-700" />

      <span class="text-xs text-gray-400">Model:</span>
      <select
        v-model="model"
        :disabled="modelLoading"
        class="text-xs bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded px-2 py-0.5 text-gray-700 dark:text-gray-200 cursor-pointer disabled:opacity-50"
      >
        <option v-if="modelLoading" value="">加载中...</option>
        <option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>

    <!-- Input row -->
    <div class="flex items-end gap-3 px-4 py-3">
      <div class="flex-1 relative">
        <textarea
          v-model="taskInput"
          @keydown="onKeydown"
          :disabled="isSubmitting"
          rows="2"
          placeholder="输入任务描述... (Ctrl+Enter 提交)"
          class="w-full resize-none rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 pr-10 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-hermes-500/30 focus:border-hermes-500 transition-colors disabled:opacity-50"
        />
        <!-- Character count -->
        <span class="absolute bottom-2 right-3 text-[10px] text-gray-400">
          {{ taskInput.length }}
        </span>
      </div>

      <button
        @click="submitTask"
        :disabled="!canSubmit"
        :class="[
          'flex items-center gap-1.5 px-4 py-2 rounded-xl font-medium text-sm transition-all shrink-0',
          canSubmit
            ? 'bg-hermes-600 hover:bg-hermes-700 text-white shadow-sm hover:shadow-md'
            : 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
        ]"
      >
        <svg v-if="!isSubmitting" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <svg v-else class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        {{ isSubmitting ? '启动中...' : '启动任务' }}
      </button>
    </div>

    <!-- Task running indicator -->
    <div v-if="store.isTaskRunning" class="px-4 pb-2">
      <div class="flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400">
        <div class="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
        任务执行中... (ID: {{ store.activeTaskId }})
        <button
          @click="store.clearCurrentTask()"
          class="ml-auto text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>
