// 工作台的常量与纯函数（从 Workspace.vue 拆出，D-026）。
// 只放"不懂 Vue、不懂请求"的东西：常量表 + 纯函数，任何组件都能直接用。

// 字号三档：改的是 html 的 font-size，全站 rem 字号跟着缩放，档位记在本地
export const FONT_SCALES = [
  { key: 'small', label: '小', root: '93.75%' },
  { key: 'normal', label: '标准', root: '100%' },
  { key: 'large', label: '大', root: '112.5%' },
]

// 左栏「规划文书」：界面上只是说明，真正的文件在仓库里（D-008 已记这个缺口）
export const repoDocs = [
  { name: 'PLAN.md', note: '要什么', text: '仓库根目录 · 唯一事实源：做什么、不做什么、验收标准。Agent 每次对话自动读它。' },
  { name: 'DECISIONS.md', note: '为什么', text: '仓库根目录 · 已经定过的决策与踩过的坑，只追加不改。指派不改变状态就是 D-005。' },
  { name: 'docs/WORKFLOW.md', note: '怎么干', text: 'docs/ 下 · 每轮节奏：产出 → 人拍板 → 落盘。一轮只推进一个能验证的小步。' },
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
