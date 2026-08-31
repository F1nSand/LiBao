import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { mockApiPlugin } from './src/mock/plugin'

// https://vitejs.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const useMock = env.VITE_USE_MOCK !== 'false'
  const apiProxy = env.VITE_API_PROXY ?? 'http://localhost:8000'
  const proxy = useMock ? undefined : { '/api': { target: apiProxy, changeOrigin: true } }

  return {
    plugins: [vue(), ...(command === 'serve' && useMock ? [mockApiPlugin()] : [])],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      // mock 关闭时走代理到后端；SSE 流透传（无特殊处理）
      proxy,
    },
    build: {
      chunkSizeWarningLimit: 1200,
    },
  }
})
