<script setup lang="ts">
import SidebarNav from '@/components/layout/SidebarNav.vue'
import TopBar from '@/components/layout/TopBar.vue'
</script>

<template>
  <div class="app-shell">
    <SidebarNav />
    <div class="app-body">
      <TopBar />
      <main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100%;
}
.app-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.app-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
