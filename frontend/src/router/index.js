import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  // 工作台 v2 已确认为默认首页（D-009）；旧工作台保留在 /home，方便随时对照与回退
  { path: '/', name: 'workspace', component: () => import('../views/Workspace.vue'), meta: { title: '工作台' } },
  { path: '/workspace', redirect: '/' },
  { path: '/home', name: 'home', component: () => import('../views/HomeView.vue'), meta: { title: '工作台（旧版）' } },
  { path: '/overview', name: 'overview', component: () => import('../views/Dashboard.vue'), meta: { title: '总览' } },
  { path: '/board', name: 'board', component: () => import('../views/ProjectBoard.vue'), meta: { title: '项目看板' } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeBase.vue'), meta: { title: '项目记忆' } },
  { path: '/chat', redirect: '/home' },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
