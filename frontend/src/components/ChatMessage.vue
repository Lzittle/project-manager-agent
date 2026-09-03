<template>
  <div class="chat-row" :class="role">
    <div class="avatar" :class="role">
      <el-icon v-if="role === 'assistant'"><MagicStick /></el-icon>
      <el-icon v-else><User /></el-icon>
    </div>
    <div class="msg-col">
      <div class="bubble" v-html="rendered" />
      <!-- Agent 执行轨迹：展示回复背后实际调用的工具步骤 -->
      <div v-if="role === 'assistant' && trace && trace.length" class="trace">
        <div class="trace-head" @click="open = !open">
          <span class="trace-title">Agent 执行过程</span>
          <el-tag size="small" effect="plain" round>{{ trace.length }} 步</el-tag>
          <span class="trace-caret">{{ open ? '收起' : '展开' }}</span>
        </div>
        <div v-if="open" class="trace-body">
          <div v-for="(s, i) in trace" :key="i" class="trace-step">
            <span class="step-dot" :class="s.ok ? 'ok' : 'err'" />
            <div class="step-main">
              <div class="step-line">
                <span class="step-label">{{ s.label }}</span>
                <span class="step-detail">{{ s.detail }}</span>
              </div>
              <div class="step-meta">
                <span class="step-ms">{{ fmtMs(s.ms) }}</span>
                <button
                  v-for="(rf, j) in (s.refs || [])"
                  :key="j"
                  class="ref-chip"
                  :class="rf.kind"
                  :title="rf.kind === 'project' ? '打开项目看板' : '打开所属项目看板'"
                  @click.stop="$emit('goto', rf)"
                >
                  <span class="ref-kind">{{ rf.kind === 'project' ? '项目' : '任务' }}</span>
                  {{ rf.title }} ›
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { MagicStick, User } from '@element-plus/icons-vue'

const props = defineProps({
  role: { type: String, required: true }, // user | assistant
  content: { type: String, default: '' },
  trace: { type: Array, default: () => [] }, // Agent 执行轨迹步骤（assistant 专属）
})
defineEmits(['goto'])
const open = ref(true) // 轨迹默认展开，让用户一眼看到 Agent 干了什么

function fmtMs(ms) {
  if (ms == null) return ''
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

// 轻量 markdown 子集渲染（**加粗**、`行内代码`、#标题、- 列表、换行），避免引入额外依赖
function miniMd(text) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const lines = esc(text).split('\n')
  const html = []
  let listOpen = false
  for (const line of lines) {
    let l = line
    if (/^\s*$/.test(l)) { if (listOpen) { html.push('</ul>'); listOpen = false } html.push('<div style="height:6px"></div>'); continue }
    if (/^#{1,3}\s/.test(l)) {
      if (listOpen) { html.push('</ul>'); listOpen = false }
      const level = l.match(/^(#{1,3})\s/)[1].length
      const inner = l.replace(/^#{1,3}\s/, '')
      html.push(`<div style="font-weight:700;font-size:${level === 1 ? 15 : 14}px;margin:4px 0">${inner}</div>`)
      continue
    }
    if (/^[-*]\s/.test(l)) {
      l = l.replace(/^[-*]\s/, '')
      if (!listOpen) { html.push('<ul style="margin:4px 0;padding-left:18px">'); listOpen = true }
      html.push(`<li>${l}</li>`)
      continue
    }
    if (/^\d+\.\s/.test(l)) {
      l = l.replace(/^\d+\.\s/, '')
      if (!listOpen) { html.push('<ul style="margin:4px 0;padding-left:18px;list-style:decimal">'); listOpen = true }
      html.push(`<li>${l}</li>`)
      continue
    }
    if (listOpen) { html.push('</ul>'); listOpen = false }
    html.push(`<div>${l}</div>`)
  }
  if (listOpen) html.push('</ul>')
  let out = html.join('')
  out = out.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
  out = out.replace(/`([^`]+)`/g, '<code style="background:#f0f2f5;padding:1px 5px;border-radius:4px;font-size:12px">$1</code>')
  return out
}

const rendered = computed(() => miniMd(props.content))
</script>

<style scoped>
.chat-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.chat-row.user { flex-direction: row-reverse; }
.msg-col { max-width: 78%; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
.chat-row.user .msg-col { align-items: flex-end; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; color: #fff; font-size: 18px;
}
.avatar.assistant { background: #409eff; }
.avatar.user { background: #67c23a; }
.bubble {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
  max-width: 100%;
}
.assistant .bubble { background: #fff; border: 1px solid #e4e7ed; color: #303133; }
.user .bubble { background: #409eff; color: #fff; }

/* ---------- Agent 执行轨迹 ---------- */
.trace { margin-top: 8px; width: 100%; border: 1px solid #e4e7ed; border-radius: 8px; overflow: hidden; background: #fafbfc; }
.trace-head {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; cursor: pointer; user-select: none;
  border-bottom: 1px solid #ebeef5;
}
.trace-title { font-size: 13px; font-weight: 600; color: #606266; }
.trace-caret { margin-left: auto; font-size: 12px; color: #909399; }
.trace-body { padding: 6px 10px 8px; }
.trace-step { display: flex; gap: 8px; padding: 5px 0; }
.step-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; }
.step-dot.ok { background: #67c23a; }
.step-dot.err { background: #f56c6c; }
.step-main { flex: 1; min-width: 0; }
.step-line { font-size: 13px; line-height: 1.6; }
.step-label { font-weight: 600; color: #303133; margin-right: 6px; }
.step-detail { color: #606266; }
.step-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 2px; }
.step-ms { font-size: 12px; color: #b1b3b8; }
.ref-chip {
  display: inline-flex; align-items: center; gap: 4px;
  border: none; border-radius: 4px;
  font-size: 12px; line-height: 1; padding: 3px 7px;
  cursor: pointer; background: #ecf5ff; color: #409eff;
}
.ref-chip:hover { background: #d9ecff; }
.ref-chip.task { background: #f0f9eb; color: #67c23a; }
.ref-chip.task:hover { background: #e1f3d8; }
.ref-kind { opacity: 0.75; }
</style>
