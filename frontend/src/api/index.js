// HTTP 封装：统一 axios 实例 + 各资源 API
//
// 轮 3（D-030）新增登录能力，但**不替换老路径**：
//   - 未登录 → 仍固定演示用户 DEMO_USER_ID=1（seed 用户 alice），演示脚本/评测/探针照旧可用；
//   - 已登录 → 每个请求自动带 `Authorization: Bearer <token>`，`user_id` 换成登录账号 id。
// 会话（token + 身份）由 stores/auth.js 持久化到 localStorage，本文件只负责读取与注入，
// 这样刷新页面、直接命中任意接口都不会丢身份。
import axios from 'axios'

export const DEMO_USER_ID = 1 // 未登录时的演示身份（对应 seed 用户 alice）

export const TOKEN_KEY = 'squad.token'
export const USER_KEY = 'squad.user'

// ---------- 会话读取（每次取实时值，不做模块级快照） ----------
function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
}

function readUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

/** 当前请求该用的 user_id：登录了就用账号 id，没登录回退演示用户。 */
export function currentUserId() {
  return readUser()?.id ?? DEMO_USER_ID
}

const http = axios.create({
  baseURL: '/api',
  timeout: 180000, // chat/send 需等待 LLM 工具循环，放宽超时
})

// 请求拦截：有令牌就带上（登录接口本身不要求，带上也无害）
http.interceptors.request.use((config) => {
  const token = readToken()
  if (token && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    const e = new Error(msg)
    e.status = err.response?.status
    return Promise.reject(e)
  }
)

// ---------- 认证（轮 3，D-030） ----------
export const authApi = {
  // 注册即入队：账号建好的同时，名册上多一条 active 成员
  register: (data) => http.post('/auth/register', data),
  login: (data) => http.post('/auth/login', data),
  // 凭令牌拉当前身份（账号 + 认领到的名册成员）
  me: () => http.get('/auth/me'),
}

// ---------- 项目 ----------
export const projectApi = {
  list: () => http.get('/projects', { params: { user_id: currentUserId() } }),
  get: (id) => http.get(`/projects/${id}`),
  create: (data) => http.post('/projects', data, { params: { user_id: currentUserId() } }),
  update: (id, data) => http.patch(`/projects/${id}`, data),
  remove: (id) => http.delete(`/projects/${id}`),
  // 看板「一键规划」：按项目主题让 AI 自动生成并创建任务
  plan: (id) => http.post(`/projects/${id}/plan`, null, { params: { user_id: currentUserId() } }),
}

// ---------- 任务 ----------
export const taskApi = {
  list: (projectId) => http.get('/tasks', { params: { project_id: projectId } }),
  // 跨项目聚合「我」的任务（轮 4 / D-031）：一次请求拿全，替代前端逐项目拉取再过滤。
  // ⚠️ 这个接口靠令牌认人，无令牌 → 401，所以只有登录后才调（演示身份走老路径）。
  mine: () => http.get('/tasks/mine'),
  create: (data) => http.post('/tasks', data, { params: { user_id: currentUserId() } }),
  update: (id, data) => http.patch(`/tasks/${id}`, data),
  remove: (id) => http.delete(`/tasks/${id}`),
}

// ---------- 小队成员名册（D-017 / D-018） ----------
// 成员是「人」的实体：占位成员没有账号，登录后用邀请码认领；任务负责人指向成员。
export const memberApi = {
  list: () => http.get('/members'),
  create: (name) => http.post('/members', { name }),
  // 用邀请码认领占位成员（轮 3）：认领不换 member.id，原先指派的活自动归位
  claim: (inviteCode) => http.post('/members/claim', { invite_code: inviteCode }),
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
    http.post('/chat/send', { message, user_id: currentUserId(), project_id: projectId }),
  history: (projectId = null) =>
    http.get('/chat/history', {
      params: projectId
        ? { user_id: currentUserId(), project_id: projectId }
        : { user_id: currentUserId() },
    }),
  // 把本项目最近的对话整理成会议纪要存入资料库（页面「存为纪要」按钮）
  meetingSummary: (projectId) =>
    http.post('/chat/meeting-summary', { user_id: currentUserId(), project_id: projectId }),
}

export default http
