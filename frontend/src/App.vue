<script setup lang="ts">
import { onMounted } from 'vue'
import StatusBar from '@/components/StatusBar.vue'
import HistorySidebar from '@/components/HistorySidebar.vue'
import AgentCanvas from '@/components/AgentCanvas.vue'
import DrawerPanel from '@/components/DrawerPanel.vue'
import TaskInputBar from '@/components/TaskInputBar.vue'
import { useWebSocket } from '@/composables/useWebSocket'

// Initialize WebSocket connection (side-effect only, no value needed)
useWebSocket()

// Dark mode toggle
function toggleDark() {
  document.documentElement.classList.toggle('dark')
  localStorage.setItem('theme', document.documentElement.classList.contains('dark') ? 'dark' : 'light')
}

onMounted(() => {
  // Restore dark mode preference
  const saved = localStorage.getItem('theme')
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  if (saved === 'dark' || (!saved && prefersDark)) {
    document.documentElement.classList.add('dark')
  }
})
</script>

<template>
  <div class="flex flex-col h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 overflow-hidden">
    <!-- Status bar -->
    <StatusBar @toggle-dark="toggleDark" />

    <!-- Main content area -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Left sidebar: history -->
      <HistorySidebar />

      <!-- Center: canvas + right panel -->
      <div class="flex flex-1 overflow-hidden">
        <!-- Canvas (React Flow) -->
        <main class="flex-1 relative overflow-hidden">
          <AgentCanvas />
        </main>

        <!-- Right drawer: conversation logs -->
        <DrawerPanel />
      </div>
    </div>

    <!-- Bottom: task input -->
    <TaskInputBar />
  </div>
</template>
