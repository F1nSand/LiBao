<script setup lang="ts">
import SidebarNav from '@/components/layout/SidebarNav.vue'
</script>

<template>
  <div class="app-shell">
    <SidebarNav />
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100%;
}
.app-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
</style>
