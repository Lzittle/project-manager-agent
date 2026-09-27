// HTTP 封装：统一 axios 实例 + 各资源 API
// demo 阶段无登录体系，固定演示用户 USER_ID=1（对应 seed 用户 alice）
import axios from 'axios'

export const USER_ID = 1

const http = axios.create({
  baseURL: '/api',
  timeout: 180000, // chat/send 需等待 LLM 工具循环，放宽超时
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

// ---------- 项目 ----------
export const projectApi = {
  list: () => http.get('/projects', { params: { user_id: USER_ID } }),
  get: (id) => http.get(`/projects/${id}`),
  create: (data) => http.post('/projects', data, { params: { user_id: USER_ID } }),
  update: (id, data) => http.patch(`/projects/${id}`, data),
  remove: (id) => http.delete(`/projects/${id}`),
  // 看板「一键规划」：按项目主题让 AI 自动生成并创建任务
  plan: (id) => http.post(`/projects/${id}/plan`, null, { params: { user_id: USER_ID } }),
}

// ---------- 任务 ----------
export const taskApi = {
  list: (projectId) => http.get('/tasks', { params: { project_id: projectId } }),
  create: (data) => http.post('/tasks', data, { params: { user_id: USER_ID } }),
  update: (id, data) => http.patch(`/tasks/${id}`, data),
  remove: (id) => http.delete(`/tasks/${id}`),
}

// ---------- 小队成员名册（D-017 / D-018） ----------
// 成员是「人」的实体：占位成员没有账号，注册后认领；任务负责人指向成员。
export const memberApi = {
  list: () => http.get('/members'),
  create: (name) => http.post('/members', { name }),
}

// ---------- 知识库文档 ----------
export const knowledgeApi = {
  list: (projectId) => http.get(`/projects/${projectId}/documents`),
  upload: (projectId, file, title) => {
    const form = new FormData()
    form.append('file', file)
    if (title) form.append('title', title)
    return http.post(`/projects/${projectId}/documents`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  // 录入会议纪要（后端自动向量化 → 项目长期记忆，可被 Agent RAG 检索）
  meeting: (projectId, title, content) => {
    const form = new FormData()
    form.append('title', title)
    form.append('content', content)
    return http.post(`/projects/${projectId}/meetings`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  remove: (docId) => http.delete(`/documents/${docId}`),
}

// ---------- 对话 ----------
export const chatApi = {
  send: (message, projectId = null) =>
    http.post('/chat/send', { message, user_id: USER_ID, project_id: projectId }),
  history: (projectId = null) =>
    http.get('/chat/history', {
      params: projectId
        ? { user_id: USER_ID, project_id: projectId }
        : { user_id: USER_ID },
    }),
  // 把本项目最近的对话整理成会议纪要存入资料库（页面「存为纪要」按钮）
  meetingSummary: (projectId) =>
    http.post('/chat/meeting-summary', { user_id: USER_ID, project_id: projectId }),
}

export default http
