<script setup lang="ts">
import { computed } from 'vue'
import { getBezierPath, type EdgeProps } from '@vue-flow/core'

const props = defineProps<EdgeProps>()

const pathData = computed(() => {
  const [p] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: props.sourcePosition || 2,
    targetPosition: props.targetPosition || 0,
  })
  return p
})

const edgeStatus = computed(() => (props.data as any)?.status || 'pending')

const strokeColor = computed(() => ({
  pending: '#94a3b8', active: '#8b5cf6', completed: '#22c55e', failed: '#ef4444',
} as Record<string, string>)[edgeStatus.value] || '#94a3b8')

const midX = computed(() => (props.sourceX + props.targetX) / 2 - 30)
const midY = computed(() => (props.sourceY + props.targetY) / 2 - 12)
</script>

<template>
  <g>
    <defs>
      <marker :id="`arrow-${id}`" viewBox="0 0 10 10" refX="10" refY="5"
        markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" :fill="strokeColor" />
      </marker>
    </defs>

    <!-- Larger click target -->
    <path :d="pathData" fill="none" stroke="transparent" stroke-width="12" />

    <!-- Main edge -->
    <path
      :d="pathData"
      fill="none"
      :stroke="strokeColor"
      :stroke-width="edgeStatus === 'active' ? 2.5 : 1.5"
      :stroke-dasharray="edgeStatus === 'pending' ? '5,5' : 'none'"
      :marker-end="`url(#arrow-${id})`"
      class="transition-all duration-300"
    />

    <!-- Animated active edge -->
    <path
      v-if="edgeStatus === 'active'"
      :d="pathData"
      fill="none"
      stroke="#8b5cf6"
      stroke-width="2"
      stroke-dasharray="8,8"
      class="animate-dash"
    />

    <!-- Status badge -->
    <foreignObject
      v-if="edgeStatus !== 'pending'"
      :x="midX" :y="midY"
      width="60" height="24"
      class="overflow-visible"
    >
      <div
        class="flex items-center justify-center rounded-full text-xs font-medium px-2 py-0.5"
        :class="{
          'bg-purple-100 dark:bg-purple-900/60 text-purple-600 dark:text-purple-300': edgeStatus === 'active',
          'bg-green-100 dark:bg-green-900/60 text-green-700 dark:text-green-300': edgeStatus === 'completed',
          'bg-red-100 dark:bg-red-900/60 text-red-700 dark:text-red-300': edgeStatus === 'failed',
        }"
      >
        {{ edgeStatus === 'active' ? '执行中' : edgeStatus === 'completed' ? '完成' : '失败' }}
      </div>
    </foreignObject>
  </g>
</template>

<style scoped>
@keyframes dash { to { stroke-dashoffset: -16; } }
.animate-dash { animation: dash 0.5s linear infinite; }
</style>
