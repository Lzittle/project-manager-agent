<template>
  <div class="chat-row" :class="role">
    <div class="avatar" :class="role">
      <el-icon v-if="role === 'assistant'"><MagicStick /></el-icon>
      <el-icon v-else><User /></el-icon>
    </div>
    <div class="msg-col">
      <div class="who" :class="role">
        {{ role === 'assistant' ? 'Squad' : '你' }}
      </div>
      <div class="bubble" :class="role" v-html="rendered" />
      <!-- Agent 执行轨迹：展示回复背后实际调用的工具步骤 -->
      <div v-if="role === 'assistant' && trace && trace.length" class="trace">
        <div class="trace-head" @click="open = !open">
          <span class="trace-pulse" :class="trace.every((s) => s.ok) ? 'ok' : 'part'" />
          <span class="trace-title">Agent 执行过程 · {{ trace.length }} 步</span>
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
                <span v-if="s.ms != null" class="step-ms">{{ fmtMs(s.ms) }}</span>
                <button
                  v-for="(rf, j) in (s.refs || [])"
                  :key="j"
                  class="ref-chip"
                  :class="rf.kind"
                  :title="rf.kind === 'project' ? '打开该项目看板' : '打开所属项目看板'"
                  @click.stop="$emit('goto', rf)"
                >
                  {{ rf.kind === 'project' ? '项目' : '任务' }} · {{ rf.title }}
                  <span class="ref-arrow">›</span>
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
    if (/^\s*$/.test(l)) { if (listOpen) { html.push('</ul>'); listOpen = false } html.push('<div class="mm-gap"></div>'); continue }
    if (/^#{1,3}\s/.test(l)) {
      if (listOpen) { html.push('</ul>'); listOpen = false }
      const level = l.match(/^(#{1,3})\s/)[1].length
      const inner = l.replace(/^#{1,3}\s/, '')
      html.push(`<div class="mm-h${level}">${inner}</div>`)
      continue
    }
    if (/^[-*]\s/.test(l)) {
      l = l.replace(/^[-*]\s/, '')
      if (!listOpen) { html.push('<ul class="mm-list">'); listOpen = true }
      html.push(`<li>${l}</li>`)
      continue
    }
    if (/^\d+\.\s/.test(l)) {
      l = l.replace(/^\d+\.\s/, '')
      if (!listOpen) { html.push('<ul class="mm-list mm-ol">'); listOpen = true }
      html.push(`<li>${l}</li>`)
      continue
    }
    if (listOpen) { html.push('</ul>'); listOpen = false }
    html.push(`<div>${l}</div>`)
  }
  if (listOpen) html.push('</ul>')
  let out = html.join('')
  out = out.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
  out = out.replace(/`([^`]+)`/g, '<code class="mm-code">$1</code>')
  return out
}

const rendered = computed(() => miniMd(props.content))
</script>

<style scoped>
.chat-row { display: flex; gap: 10px; margin-bottom: 18px; align-items: flex-start; }
.chat-row.user { flex-direction: row-reverse; }

.msg-col { max-width: 82%; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
.chat-row.user .msg-col { align-items: flex-end; }

.who {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  margin: 0 4px 3px;
  letter-spacing: 0.04em;
}

.avatar {
  width: 32px; height: 32px; margin-top: 18px;
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; color: #fff; font-size: 16px;
  box-shadow: var(--el-box-shadow-lighter);
}
.avatar.assistant { background: linear-gradient(135deg, #0d9488, #0f766e 60%, #0b4a45); }
.avatar.user { background: var(--el-fill-color-dark); color: var(--el-text-color-regular); }

.bubble {
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
  max-width: 100%;
}
.assistant .bubble {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  color: var(--el-text-color-primary);
  border-top-left-radius: 4px;
  box-shadow: var(--el-box-shadow-light);
}
.user .bubble {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  color: var(--el-text-color-primary);
  border-top-right-radius: 4px;
}

/* 轻量 markdown 内部排版 */
.bubble :deep(.mm-h1) { font-size: 15px; font-weight: 700; margin: 8px 0 4px; }
.bubble :deep(.mm-h2), .bubble :deep(.mm-h3) { font-size: 14px; font-weight: 700; margin: 6px 0 2px; }
.bubble :deep(.mm-list) { margin: 4px 0; padding-left: 20px; }
.bubble :deep(.mm-ol) { list-style: decimal; }
.bubble :deep(.mm-gap) { height: 7px; }
.bubble :deep(.mm-code) {
  background: var(--el-fill-color);
  border: 1px solid var(--el-border-color-extra-light);
  padding: 1px 5px;
  border-radius: 5px;
  font-size: 12px;
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  color: var(--el-color-primary-dark-2);
}

/* ---------- Agent 执行轨迹 ---------- */
.trace {
  margin-top: 8px;
  width: 100%;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  overflow: hidden;
  background: var(--el-fill-color-lighter);
}
.trace-head {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; cursor: pointer; user-select: none;
}
.trace-pulse { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.trace-pulse.ok { background: var(--el-color-success); box-shadow: 0 0 0 3px var(--el-color-success-light-9); }
.trace-pulse.part { background: var(--el-color-warning); box-shadow: 0 0 0 3px var(--el-color-warning-light-9); }
.trace-title { font-size: 12px; font-weight: 600; color: var(--el-text-color-regular); }
.trace-caret { margin-left: auto; font-size: 12px; color: var(--el-text-color-secondary); }

.trace-body { padding: 4px 0 8px; }
.trace-step {
  display: flex; gap: 10px;
  padding: 7px 14px 7px 12px;
  position: relative;
}
.trace-step + .trace-step::before {
  content: '';
  position: absolute;
  left: 15px; top: 0; height: 100%;
  border-left: 1px dashed var(--el-border-color-light);
}
.step-dot {
  width: 7px; height: 7px; border-radius: 50%;
  margin-top: 6px; flex-shrink: 0; position: relative; z-index: 1;
}
.step-dot.ok { background: var(--el-color-success); }
.step-dot.err { background: var(--el-color-danger); }
.step-main { flex: 1; min-width: 0; }
.step-line { font-size: 13px; line-height: 1.6; }
.step-label { font-weight: 600; color: var(--el-text-color-primary); margin-right: 4px; }
.step-detail { color: var(--el-text-color-regular); word-break: break-word; }
.step-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 3px; }
.step-ms { font-size: 11px; color: var(--el-text-color-placeholder); font-variant-numeric: tabular-nums; }
.ref-chip {
  display: inline-flex; align-items: center; gap: 4px;
  border: none; border-radius: 7px;
  font-size: 12px; line-height: 1.4; padding: 3px 8px;
  cursor: pointer;
}
.ref-chip.project { background: var(--el-color-primary-light-9); color: var(--el-color-primary-dark-2); }
.ref-chip.project:hover { background: var(--el-color-primary-light-8); }
.ref-chip.task { background: var(--el-color-success-light-9); color: var(--el-color-success-dark-2); }
.ref-chip.task:hover { background: var(--el-color-success-light-8); }
.ref-arrow { opacity: 0.6; }
</style>
