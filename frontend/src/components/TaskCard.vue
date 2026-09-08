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
      <span v-if="isBlocked" class="tc-blocked" title="前置任务尚未完成，完成后即可开工">
        <el-icon><Lock /></el-icon> 待解锁
      </span>
      <span v-else-if="task.depends_on?.length" class="tc-dep" title="有前置任务待完成">
        <el-icon><Link /></el-icon> {{ task.depends_on.length }}
      </span>
    </div>
    <div class="tc-title">{{ task.title }}</div>
    <div v-if="task.description" class="tc-desc">{{ task.description }}</div>
    <div class="tc-foot">
      <div class="tc-meta">
        <span class="tc-status" :class="'st-' + task.status">
          <i class="tc-dot" />{{ statusText }}
        </span>
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
const STATUS_TEXT = { todo: '待办', doing: '进行中', done: '已完成' }

const priText = computed(() => PRIORITY[props.task.priority]?.text || props.task.priority)
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
/* Linear 式任务卡：发丝边框 + 极柔阴影，状态用「点」而非彩色大标签 */
.task-card {
  background: var(--el-bg-color);
  border-radius: var(--squad-radius-card);
  padding: 12px 14px;
  margin-bottom: 10px;
  border: 1px solid var(--el-border-color-light);
  box-shadow: var(--el-box-shadow-lighter);
  cursor: grab;
  transition: box-shadow 0.15s var(--squad-ease), border-color 0.15s var(--squad-ease),
              transform 0.15s var(--squad-ease);
}
.task-card:hover {
  box-shadow: var(--squad-shadow-hover);
  border-color: var(--el-color-primary-light-7);
  transform: translateY(-1px);
}
.task-card.blocked {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}
.task-card:active { cursor: grabbing; }
.tc-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }

/* 优先级：克制的小描边 pill（不再实心色块） */
.tc-pri {
  font-size: 11px;
  line-height: 16px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid transparent;
}
.tc-pri.high { color: #dc2626; border-color: #fecaca; background: #fef2f2; }
.tc-pri.medium { color: #b88230; border-color: #f3d19e; background: #fdf6ec; }
.tc-pri.low { color: var(--el-text-color-secondary); border-color: var(--el-border-color); background: var(--el-fill-color-lighter); }

/* 依赖 / 阻塞徽记 */
.tc-blocked {
  font-size: 11px;
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  padding: 0 8px;
  line-height: 16px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.tc-dep {
  font-size: 11px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  padding: 0 8px;
  line-height: 16px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

/* 状态：单色点 + 文字（克制，Linear 口吻） */
.tc-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.tc-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.st-todo .tc-dot { background: var(--el-text-color-placeholder); }
.st-doing .tc-dot { background: var(--el-color-primary); }
.st-done .tc-dot { background: var(--el-color-success); }
.st-done { color: var(--el-text-color-secondary); }

.tc-title { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); margin-bottom: 4px; }
.tc-desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tc-foot { display: flex; justify-content: space-between; align-items: center; }
.tc-meta { display: flex; align-items: center; gap: 10px; }
.tc-assignee {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
</style>
