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
/* Linear 式任务卡 → v5（D-013）：surface 底 + line 发丝边；状态用 8px 点；优先级用四色软块（只做底） */
.task-card {
  background: var(--p-surface);
  border-radius: var(--p-r-sm);
  padding: 12px 14px;
  margin-bottom: 10px;
  border: 1px solid var(--p-line);
  box-shadow: var(--p-shadow-1);
  cursor: grab;
  transition: box-shadow 0.15s var(--squad-ease), border-color 0.15s var(--squad-ease),
              transform 0.15s var(--squad-ease);
}
.task-card:hover {
  box-shadow: var(--squad-shadow-hover);
  border-color: var(--p-brand-line);
  transform: translateY(-1px);
}
/* 阻塞：沙色软底（v5 唯一允许「底带色」的用法），不再用 Element warning 浅色变量 */
.task-card.blocked {
  border-color: color-mix(in srgb, var(--p-on-sand) 30%, var(--p-line));
  background: color-mix(in srgb, var(--p-block-sand) 42%, var(--p-surface));
}
.task-card:active { cursor: grabbing; }
.tc-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }

/* 优先级：小软块（rose / sand / plain），取代原先 6 个一次性硬编码色值 */
.tc-pri {
  font-size: var(--p-fs-tag);
  line-height: 1rem;
  padding: 0 7px;
  border-radius: var(--p-r-xs);
}
.tc-pri.high { color: var(--p-on-rose); background: var(--p-block-rose); }
.tc-pri.medium { color: var(--p-on-sand); background: var(--p-block-sand); }
.tc-pri.low { color: var(--p-ink-2); background: var(--p-block-plain); }

/* 依赖 / 阻塞徽记 */
.tc-blocked {
  font-size: var(--p-fs-tag);
  color: var(--p-on-sand);
  background: var(--p-block-sand);
  padding: 0 8px;
  line-height: 1rem;
  border-radius: var(--p-r-xs);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.tc-dep {
  font-size: var(--p-fs-tag);
  color: var(--p-brand-strong);
  background: var(--p-brand-wash);
  padding: 0 8px;
  line-height: 1rem;
  border-radius: var(--p-r-xs);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

/* 状态：单色点 + 文字（克制，Linear 口吻） */
.tc-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--p-fs-meta);
  color: var(--p-ink-2);
}
.tc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.st-todo .tc-dot { background: var(--p-idle); }
.st-doing .tc-dot { background: var(--p-brand); }
.st-done .tc-dot { background: var(--p-ok); }
.st-done { color: var(--p-idle); }

.tc-title { font-size: var(--p-fs-title); font-weight: 600; color: var(--p-ink); margin-bottom: 4px; text-wrap: pretty; }
.tc-desc {
  font-size: var(--p-fs-meta);
  color: var(--p-ink-2);
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-wrap: pretty;
}
.tc-foot { display: flex; justify-content: space-between; align-items: center; }
.tc-meta { display: flex; align-items: center; gap: 10px; }
.tc-assignee {
  font-size: var(--p-fs-meta);
  color: var(--p-ink-2);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
</style>
