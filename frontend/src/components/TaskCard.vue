<template>
  <div
    class="task-card"
    :class="{ blocked: isBlocked }"
    draggable="true"
    @dragstart.stop="onDragStart"
    @click="$emit('open', task)"
  >
    <div class="tc-head">
      <span class="tc-pri" :class="task.priority">{{ priText }}</span>
      <span v-if="isBlocked" class="tc-blocked" title="存在未完成的前置任务，无法开工">
        <el-icon><Lock /></el-icon> 依赖阻塞
      </span>
      <span v-else-if="task.depends_on?.length" class="tc-dep" title="依赖前置任务完成">
        <el-icon><Link /></el-icon> {{ task.depends_on.length }}
      </span>
    </div>
    <div class="tc-title">{{ task.title }}</div>
    <div v-if="task.description" class="tc-desc">{{ task.description }}</div>
    <div class="tc-foot">
      <div class="tc-meta">
        <el-tag size="small" :type="statusType" effect="light" round>{{ statusText }}</el-tag>
        <span v-if="task.assignee_name" class="tc-assignee">
          <el-icon><User /></el-icon>{{ task.assignee_name }}
        </span>
      </div>
      <el-button link type="danger" size="small" @click.stop="$emit('remove', task)">
        删除
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Lock, Link, User } from '@element-plus/icons-vue'

const props = defineProps({
  task: { type: Object, required: true },
})
defineEmits(['open', 'remove'])

const PRIORITY = {
  high: { text: '高', cls: 'high' },
  medium: { text: '中', cls: 'medium' },
  low: { text: '低', cls: 'low' },
}
const STATUS_TYPE = { todo: 'info', doing: 'primary', done: 'success' }
const STATUS_TEXT = { todo: '待办', doing: '进行中', done: '已完成' }

const priText = computed(() => PRIORITY[props.task.priority]?.text || props.task.priority)
const statusType = computed(() => STATUS_TYPE[props.task.status] || 'info')
const statusText = computed(() => STATUS_TEXT[props.task.status] || props.task.status)
// 有未完成前置 → 阻塞（仅对未完成任务显示，已完成不视为阻塞）
const isBlocked = computed(() =>
  props.task.status !== 'done'
  && (props.task.blocked_by_count || 0) > 0,
)

function onDragStart(e) {
  e.dataTransfer.setData('text/task-id', String(props.task.id))
  e.dataTransfer.effectAllowed = 'move'
}
</script>

<style scoped>
.task-card {
  background: #fff;
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
  box-shadow: 0 1px 3px rgba(31, 35, 41, 0.08);
  cursor: grab;
  border: 1px solid transparent;
  border-left: 3px solid var(--el-color-primary-light-7);
  transition: box-shadow 0.2s, border-color 0.2s, transform 0.1s;
}
.task-card:hover {
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.12);
  border-color: var(--el-color-primary-light-5);
  transform: translateY(-1px);
}
.task-card.blocked {
  border-left-color: #e6a23c;
  background: linear-gradient(135deg, #fffdf7 0%, #fff 60%);
}
.task-card:active { cursor: grabbing; }
.tc-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.tc-pri {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  color: #fff;
}
.tc-pri.high { background: #f56c6c; }
.tc-pri.medium { background: #e6a23c; }
.tc-pri.low { background: #909399; }
.tc-blocked {
  font-size: 11px;
  color: #e6a23c;
  background: #fdf6ec;
  padding: 1px 8px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.tc-dep {
  font-size: 11px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  padding: 1px 8px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.tc-title { font-size: 14px; font-weight: 600; color: #1f2329; margin-bottom: 4px; }
.tc-desc {
  font-size: 12px;
  color: #8a8f99;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tc-foot { display: flex; justify-content: space-between; align-items: center; }
.tc-meta { display: flex; align-items: center; gap: 8px; }
.tc-assignee {
  font-size: 12px;
  color: #6b7280;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
</style>
