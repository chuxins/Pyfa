import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { initLocale } from './i18n'
import './style.css'

// Before the first paint, so the page is not briefly English. The server's own
// language, once /api/meta has answered, takes precedence over this guess.
initLocale()

createApp(App).use(createPinia()).mount('#app')
