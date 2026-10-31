// 工作台的常量与纯函数（从 Workspace.vue 拆出，D-026）。
// 只放"不懂 Vue、不懂请求"的东西：常量表 + 纯函数，任何组件都能直接用。

// 字号三档：改的是 html 的 font-size，全站 rem 字号跟着缩放，档位记在本地
export const FONT_SCALES = [
  { key: 'small', label: '小', root: '93.75%' },
  { key: 'normal', label: '标准', root: '100%' },
  { key: 'large', label: '大', root: '112.5%' },
]

// 左栏「开发文档」：只展示公开技术文档；产品规划与任务清单保存在私有工作区
export const repoDocs = [
  { name: 'README.md', note: '项目说明', text: '公开仓库 · 产品定位、架构、快速开始和公开能力说明。' },
  { name: 'docs/DEV_OPS.md', note: '运行维护', text: '公开仓库 · 本地启动、端口排查、重启和行为探针规则。' },
  { name: 'backend/eval/README.md', note: '评测说明', text: '公开仓库 · 离线 Agent 评测的运行方式和判定口径。' },
]

export const filters = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '未开始' },
  { key: 'doing', label: '进行中' },
]

export const STATUS = {
  todo: { label: '待办', dot: 'todo', col: '待办' },
  doing: { label: '进行中', dot: 'doing', col: '进行中' },
  done: { label: '已完成', dot: 'done', col: '已完成' },
}

export const DOC_PREVIEW_CHARS = 1500  // 资产库预览最多渲染多少字（超出部分靠框内滚动）

// 文档类型标签（doc_type 现在是三种：资料 / 会议纪要 / 对话里确认的结论笔记）
export function docTypeLabel(t) {
  return { doc: '文档', meeting: '会议纪要', note: '结论笔记' }[t] || t || '文档'
}

export function statusOf(t) {
  return STATUS[t.status] || { label: t.status, dot: 'todo', col: t.status }
}

export function isBlocked(t) {
  return t.status !== 'done' && (t.blocked_by_count || 0) > 0
}

export function dotClass(t) {
  if (isBlocked(t)) return 'lock'
  return statusOf(t).dot
}

export function priText(p) {
  return { high: '高', medium: '中', low: '低' }[p] || p || '中'
}

// 「新」= 24 小时内创建的任务：第 4 个软色块（rose）只用于这种瞬时变化
export function isFresh(t) {
  if (!t.created_at) return false
  const ms = Date.now() - new Date(t.created_at).getTime()
  return ms >= 0 && ms < 24 * 60 * 60 * 1000
}
