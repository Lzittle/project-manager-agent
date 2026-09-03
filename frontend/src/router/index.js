import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '数据仪表盘' } },
  { path: '/board', name: 'board', component: () => import('../views/ProjectBoard.vue'), meta: { title: '项目看板' } },
  { path: '/chat', name: 'chat', component: () => import('../views/ChatView.vue'), meta: { title: 'AI 对话' } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeBase.vue'), meta: { title: '知识库' } },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
