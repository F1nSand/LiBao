import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import router from './router'
import { appIcons } from './icons'

import 'element-plus/dist/index.css'
import 'highlight.js/styles/github.css'
import '@/styles/tokens.css'
import '@/styles/element-overrides.css'
import '@/styles/global.css'
import '@/styles/composer.css'
import '@/styles/markdown.css'
import { applyTheme, getStoredTheme } from '@/theme/themes'

// 首屏前应用已存主题，避免闪色
applyTheme(getStoredTheme())

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [key, component] of Object.entries(appIcons)) {
  app.component(key, component)
}

app.mount('#app')
