import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './assets/theme.css'
// 工作台样式（D-026：从 Workspace.vue 的 scoped 样式整块搬出 —— 拆组件后父组件的
// scoped 样式碰不到子组件内部；类名都以 .ws- 前缀命名空间化，放全局安全）
import './assets/workspace.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
