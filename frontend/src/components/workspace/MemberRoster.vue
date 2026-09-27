<!-- 小队成员名册（左栏）：占位成员（还没注册的人）也能被指派，邀请码发给对方认领（D-017/D-018）。 -->
<template>
  <div class="ws-roster">
    <div v-for="m in members" :key="m.id" class="ws-member" :class="{ wait: m.status !== 'active' }">
      <span class="ws-pava" :class="{ empty: m.status !== 'active' }">{{ m.name.slice(-1) }}</span>
      <span class="ws-mname">{{ m.name }}</span>
      <span v-if="m.status !== 'active'" class="ws-code">{{ m.invite_code }}</span>
      <span class="ws-tag" :class="m.status === 'active' ? 'ok' : 'wait'">
        {{ m.status === 'active' ? '已注册' : '待认领' }}
      </span>
    </div>
    <div v-if="!members.length" class="ws-empty-small">还没有成员，手填一个名字就能开始指派。</div>
    <div class="ws-addmember">
      <input
        class="ws-minput"
        type="text"
        :value="name"
        placeholder="手填名字…"
        aria-label="手填成员名字"
        @input="$emit('update:name', $event.target.value)"
        @keydown.enter="$emit('add')"
      />
      <button class="ws-btn" type="button" @click="$emit('add')">出邀请码</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  members: { type: Array, default: () => [] },
  name: { type: String, default: '' },   // v-model:name
})
defineEmits(['update:name', 'add'])
</script>
