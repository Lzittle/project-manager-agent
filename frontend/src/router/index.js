import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue'), meta: { title: '工作台' } },
  { path: '/overview', name: 'overview', component: () => import('../views/Dashboard.vue'), meta: { title: '总览' } },
  { path: '/workspace', name: 'workspace', component: () => import('../views/Workspace.vue'), meta: { title: '工作台 v2' } },
  { path: '/board', name: 'board', component: () => import('../views/ProjectBoard.vue'), meta: { title: '项目看板' } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeBase.vue'), meta: { title: '项目记忆' } },
  // 旧「AI 对话」页已并入工作台，保留路径作回跳兜底
  { path: '/chat', redirect: '/' },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
