<!-- 看板任务卡 + 就地指派浮层（D-007：不弹模态、不跳页；D-005：指派不改状态）。 -->
<template>
  <article class="ws-card" :class="{ locked: blocked }">
    <span class="ws-pri" :class="task.priority">{{ priText(task.priority) }}</span>
    <h4>{{ task.title }}</h4>
    <div v-if="blocked" class="ws-cardnote">被前置任务卡住，前置完成后可开工</div>
    <div class="ws-cardfoot">
      <button
        class="ws-whochip"
        :class="{ empty: !task.assignee_name }"
        type="button"
        :aria-expanded="open"
        :aria-label="task.assignee_name ? '改派「' + task.title + '」' : '给「' + task.title + '」指派负责人'"
        @click="$emit('toggle')"
      >
        <span class="ws-pava" :class="{ empty: !task.assignee_name }">{{ task.assignee_name ? task.assignee_name.slice(-1) : '+' }}</span>
        <span class="ws-who">{{ task.assignee_name || '指派' }}</span>
      </button>
      <span v-if="fresh" class="ws-fresh">新</span>

      <div v-if="open" class="ws-pop" role="dialog" aria-label="指派给谁">
        <div class="ws-pophead"><b>指派给谁？</b><span>选名册里的人</span></div>
        <button
          v-for="m in members"
          :key="m.id"
          class="ws-poprow"
          type="button"
          @click="$emit('assign', m)"
        >
          <span class="ws-pava" :class="{ empty: m.status !== 'active' }">{{ m.name.slice(-1) }}</span>
          <span class="ws-popname">{{ m.name }}</span>
          <span v-if="m.status !== 'active'" class="ws-code">{{ m.invite_code }}</span>
          <span class="ws-tag" :class="m.status === 'active' ? 'ok' : 'wait'">
            {{ m.status === 'active' ? '已注册' : '待认领' }}
          </span>
        </button>
        <div v-if="!members.length" class="ws-empty-small">名册还是空的，在下面填个名字。</div>
        <div class="ws-popnew">
          <input
            class="ws-minput"
            type="text"
            :value="name"
            placeholder="新成员名字…"
            aria-label="新成员名字"
            @input="$emit('update:name', $event.target.value)"
            @keydown.enter="$emit('create')"
          />
          <button class="ws-btn solid" type="button" @click="$emit('create')">新建并指派</button>
        </div>
        <p class="ws-popfoot">新建的是占位身份（带邀请码），对方注册后认领；指派不改任务状态。</p>
      </div>
    </div>
  </article>
</template>

<script setup>
import { priText } from './constants.js'

defineProps({
  task: { type: Object, required: true },
  members: { type: Array, default: () => [] },
  open: Boolean,                          // 指派浮层是否展开（由父组件决定"哪张卡开着"）
  name: { type: String, default: '' },    // 浮层里"新成员名字"输入
  fresh: Boolean,
  blocked: Boolean,
})
defineEmits(['toggle', 'assign', 'create', 'update:name'])
</script>
