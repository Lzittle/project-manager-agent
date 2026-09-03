<template>
  <div
    class="task-card"
    draggable="true"
    @dragstart.stop="onDragStart"
    @click="$emit('open', task)"
  >
    <div class="tc-head">
      <span class="tc-pri" :class="task.priority">{{ priText }}</span>
      <!-- 拖拽手柄：替代原全局 #id 展示（全局 id 会跳号，对用户无意义） -->
      <svg class="tc-grip" viewBox="0 0 10 14" fill="currentColor" aria-hidden="true">
        <circle cx="2.5" cy="2.5" r="1.4" />
        <circle cx="7.5" cy="2.5" r="1.4" />
        <circle cx="2.5" cy="7" r="1.4" />
        <circle cx="7.5" cy="7" r="1.4" />
        <circle cx="2.5" cy="11.5" r="1.4" />
        <circle cx="7.5" cy="11.5" r="1.4" />
      </svg>
    </div>
    <div class="tc-title">{{ task.title }}</div>
    <div v-if="task.description" class="tc-desc">{{ task.description }}</div>
    <div class="tc-foot">
      <el-tag size="small" :type="statusType">{{ statusText }}</el-tag>
      <el-button link type="danger" size="small" @click.stop="$emit('remove', task)">
        删除
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

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

function onDragStart(e) {
  e.dataTransfer.setData('text/task-id', String(props.task.id))
  e.dataTransfer.effectAllowed = 'move'
}
</script>

<style scoped>
.task-card {
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  cursor: grab;
  border: 1px solid transparent;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.task-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  border-color: var(--el-color-primary-light-5);
}
.task-card:active { cursor: grabbing; }
.tc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.tc-pri {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  color: #fff;
}
.tc-pri.high { background: #f56c6c; }
.tc-pri.medium { background: #e6a23c; }
.tc-pri.low { background: #909399; }
.tc-grip { color: #c0c4cc; opacity: 0.7; transition: opacity 0.2s, color 0.2s; cursor: grab; }
.task-card:hover .tc-grip { opacity: 1; color: #909399; }
.tc-title { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.tc-desc {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tc-foot { display: flex; justify-content: space-between; align-items: center; }
</style>
