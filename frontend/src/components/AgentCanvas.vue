<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { VueFlow, Panel } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import dagre from 'dagre'
import { useDashboardStore } from '@/stores/dashboard'
import type { FlowNode } from '@/types/dashboard'
import HermesNode from '@/nodes/HermesNode.vue'
import OpenClawNode from '@/nodes/OpenClawNode.vue'
import ToolNode from '@/nodes/ToolNode.vue'
import CustomEdge from '@/nodes/CustomEdge.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const store = useDashboardStore()

// Local reactive copies synced from store
const rfNodes = ref<any[]>([])
const rfEdges = ref<any[]>([])
const vueFlowRef = ref<InstanceType<typeof VueFlow> | null>(null)

const nodeTypes = {
  hermes: HermesNode,
  openclaw: OpenClawNode,
  tool: ToolNode,
}

const edgeTypes = {
  custom: CustomEdge,
}

function getLayouted(rawNodes: any[], rawEdges: any[]) {
  if (!rawNodes || rawNodes.length === 0) return { nodes: rawNodes, edges: rawEdges }

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 90, edgesep: 20 })

  rawNodes.forEach((n: any) => {
    const w = n.type === 'hermes' ? 224 : n.type === 'tool' ? 144 : 240
    const h = n.type === 'hermes' ? 160 : n.type === 'tool' ? 112 : 200
    g.setNode(n.id, { width: w, height: h })
  })
  rawEdges.forEach((e: any) => g.setEdge(e.source, e.target))

  dagre.layout(g)

  const laid = rawNodes.map((n: any) => {
    const { x, y } = g.node(n.id) || { x: 0, y: 0 }
    return { ...n, position: { x, y } }
  })

  return { nodes: laid, edges: rawEdges }
}

function syncToCanvas() {
  if (!store.nodes.length) {
    rfNodes.value = []
    rfEdges.value = []
    return
  }

  const nodes = store.nodes.map((n: FlowNode) => ({
    id: n.id,
    type: n.type || 'openclaw',
    position: n.position || { x: 0, y: 0 },
    data: n,
  }))

  const edges = store.edges.map((e: any) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: 'custom',
    data: e.data || { status: 'pending' },
  }))

  const { nodes: laid, edges: laidE } = getLayouted(nodes, edges)
  rfNodes.value = laid
  rfEdges.value = laidE

  nextTick(() => {
    vueFlowRef.value?.fitView?.({ padding: 0.15, duration: 400 })
  })
}

function onNodeClick(nodeMouseEvent: any) {
  const { node } = nodeMouseEvent
  store.setSelectedNode(node.id)
  store.setDrawerOpen(true)
}

function onPaneClick() {
  store.setSelectedNode(null)
}

function onMoveEnd(viewport: { flowTransform: any }) {
  store.setViewport(viewport.flowTransform)
}

onMounted(async () => {
  await nextTick()
  if (store.nodes.length > 0) {
    syncToCanvas()
    await nextTick()
    vueFlowRef.value?.fitView?.({ padding: 0.15, duration: 600 })
  }
})

watch(() => store.nodes, () => syncToCanvas(), { deep: true })
watch(() => store.edges, () => syncToCanvas(), { deep: true })
</script>

<template>
  <div class="relative w-full h-full bg-gray-50/50 dark:bg-gray-900/50">
    <!-- Empty state -->
    <div
      v-if="rfNodes.length === 0"
      class="absolute inset-0 flex flex-col items-center justify-center gap-4 z-10 pointer-events-none"
    >
      <div class="w-20 h-20 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 dark:from-blue-900/30 dark:to-purple-900/30 flex items-center justify-center">
        <svg class="w-10 h-10 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.455 2.456z" />
        </svg>
      </div>
      <div class="text-center">
        <p class="text-gray-500 dark:text-gray-400 text-sm font-medium">暂无任务</p>
        <p class="text-gray-400 dark:text-gray-500 text-xs mt-1">在下方输入任务开始协作</p>
      </div>
    </div>

    <!-- Vue Flow -->
    <VueFlow
      ref="vueFlowRef"
      :nodes="rfNodes"
      :edges="rfEdges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :default-viewport="{ x: 100, y: 50, zoom: 1 }"
      fit-view-on-init
      :only-render-visible-nodes="false"
      :min-zoom="0.2"
      :max-zoom="2"
      :snap-to-grid="true"
      :snap-grid="[16, 16]"
      @node-click="onNodeClick"
      @pane-click="onPaneClick"
      @move-end="onMoveEnd"
    >
      <Background pattern-color="#e5e7eb" :gap="16" />
      <Controls position="bottom-right" />
      <MiniMap
        position="bottom-left"
        :node-color="(n: any) => n.type === 'hermes' ? '#3b82f6' : n.type === 'tool' ? '#eab308' : '#8b5cf6'"
        :node-stroke-width="2"
        pannable
        zoomable
      />

      <Panel position="top-right" class="flex gap-2">
        <button
          @click="() => vueFlowRef?.fitView?.({ padding: 0.15 })"
          class="px-3 py-1.5 text-xs bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >重置视图</button>
        <button
          v-if="store.activeTaskId"
          @click="() => store.setDrawerOpen(true)"
          class="px-3 py-1.5 text-xs bg-blue-500 text-white rounded-lg shadow-sm hover:bg-blue-600 transition-colors"
        >查看详情</button>
      </Panel>
    </VueFlow>
  </div>
</template>
