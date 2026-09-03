<template>
  <div class="chat-row" :class="role">
    <div class="avatar" :class="role">
      <el-icon v-if="role === 'assistant'"><MagicStick /></el-icon>
      <el-icon v-else><User /></el-icon>
    </div>
    <div class="bubble" v-html="rendered" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { MagicStick, User } from '@element-plus/icons-vue'

const props = defineProps({
  role: { type: String, required: true }, // user | assistant
  content: { type: String, default: '' },
})

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
.avatar {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; color: #fff; font-size: 18px;
}
.avatar.assistant { background: #409eff; }
.avatar.user { background: #67c23a; }
.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.assistant .bubble { background: #fff; border: 1px solid #e4e7ed; color: #303133; }
.user .bubble { background: #409eff; color: #fff; }
</style>
