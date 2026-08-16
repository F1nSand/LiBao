import { createRouter, createWebHistory } from 'vue-router'
import { routes } from './routes'
import { installGuard } from './guard'

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

installGuard(router)

export default router
