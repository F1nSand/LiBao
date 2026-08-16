<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import SidebarNav from '@/components/layout/SidebarNav.vue'
import TopBar from '@/components/layout/TopBar.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

onMounted(() => {
  authStore.hydrate()
})

const isAppLayout = computed(() => {
  const meta = route.meta as { requiresAuth?: boolean }
  return !!meta?.requiresAuth && authStore.isAuthenticated
})

async function onLogout() {
  await authStore.logout()
  router.replace('/login')
}
</script>

<template>
  <div v-if="isAppLayout" class="app-shell">
    <SidebarNav />
    <div class="app-body">
      <TopBar :user="authStore.user" @logout="onLogout" />
      <main class="app-main">
        <router-view />
      </main>
    </div>
  </div>
  <router-view v-else />
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
