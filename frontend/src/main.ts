import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './app/App.vue'
import router from './app/router'
import './components/common/base.css'
import './components/common/teaching.css'

createApp(App).use(createPinia()).use(router).mount('#app')
