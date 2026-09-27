<!-- 现场（右栏）：预览列表 → 全屏看板；或「我的任务」跨项目视图。纯展示，状态都在父组件。 -->
<template>
  <aside class="ws-live" :class="{ 'is-full': liveFull }" aria-label="现场">
    <div class="ws-livehead">
      <div class="ws-livetitle">
        <b>{{ scope === 'me' ? '我的任务' : '现场 · ' + (projectName || '全局') }}</b>
        <span>{{ summary }}</span>
      </div>
      <div class="ws-liveacts">
        <span class="ws-follow"><i class="ws-followdot" aria-hidden="true"></i>跟随对话</span>
        <button class="ws-btn" type="button" @click="$emit('update:liveFull', !liveFull)">
          {{ liveFull ? '退出全屏' : '全屏' }}
        </button>
      </div>
    </div>

    <div v-if="scope === 'team' && hasProject" class="ws-filters" role="group" aria-label="任务筛选">
      <button
        v-for="f in filters"
        :key="f.key"
        class="ws-chip"
        :class="{ on: filter === f.key }"
        type="button"
        @click="$emit('update:filter', f.key)"
      >{{ f.label }}</button>
    </div>

    <!-- 我的任务：跨项目 -->
    <template v-if="scope === 'me'">
      <div v-for="group in myGroups" :key="group.project" class="ws-mygroup">
        <div class="ws-myproj">{{ group.project }}</div>
        <div v-for="t in group.tasks" :key="t.id" class="ws-myitem">
          <b>{{ t.title }}</b>
          <span>{{ statusOf(t).label }}</span>
        </div>
      </div>
      <div v-if="!myGroups.length" class="ws-empty-small">当前没有派给 {{ meName }} 的任务。</div>
    </template>

    <!-- 全队：预览（默认）或看板（全屏） -->
    <template v-else>
      <!-- 全局：各项目任务分布（队长视野），点一行进入那个项目 -->
      <div v-if="!hasProject">
        <div class="ws-empty-small">还没绑定项目。下面是全队的任务分布，点一行进入那个项目。</div>
        <button
          v-for="p in overview"
          :key="p.id"
          class="ws-row"
          type="button"
          @click="$emit('open-project', p.id)"
        >
          <span class="ws-rowmain">
            <span class="ws-rowtitle">{{ p.name }}</span>
            <span class="ws-rowmeta">{{ p.total }} 条任务 · 进行中 {{ p.doing }}<template v-if="p.blocked"> · 待解锁 {{ p.blocked }}</template></span>
          </span>
          <span class="ws-arrow">›</span>
        </button>
        <div v-if="!overview.length" class="ws-empty-small">还没有项目。</div>
      </div>
      <div v-else-if="!visibleTasks.length" class="ws-empty-small">
        这个项目还没有任务，跟左边说一句就会长出来。
      </div>
      <div v-else-if="!liveFull" class="ws-preview-list">
        <button
          v-for="t in visibleTasks.slice(0, 4)"
          :key="t.id"
          class="ws-row"
          type="button"
          @click="$emit('update:liveFull', true)"
        >
          <i class="ws-dot" :class="dotClass(t)" aria-hidden="true" />
          <span class="ws-rowmain">
            <span class="ws-rowtitle">{{ t.title }}</span>
            <span v-if="isBlocked(t)" class="ws-rowwarn">待解锁</span>
          </span>
          <span v-if="isFresh(t)" class="ws-fresh">新</span>
          <span class="ws-pava" :class="{ empty: !t.assignee_name }">{{ t.assignee_name ? t.assignee_name.slice(-1) : '+' }}</span>
        </button>
        <div v-if="visibleTasks.length > 4" class="ws-more">
          还有 {{ visibleTasks.length - 4 }} 条，点开看全部
        </div>
        <div class="ws-hint">点上面任意一条 → 展开成全屏看板</div>
      </div>
      <div v-else class="ws-board" :class="{ one: filter !== 'all' }">
        <section v-for="col in visibleColumns" :key="col.key" class="ws-col" :class="'ws-col-' + col.key">
          <div class="ws-colhead">
            <i class="ws-dot" :class="col.dot" aria-hidden="true" />
            <span>{{ col.label }}</span>
            <b>{{ col.tasks.length }}</b>
          </div>
          <BoardCard
            v-for="t in col.tasks"
            :key="t.id"
            :task="t"
            :members="members"
            :fresh="isFresh(t)"
            :blocked="isBlocked(t)"
            :open="assignFor === t.id"
            :name="assignName"
            @toggle="$emit('toggle-assign', t)"
            @assign="(m) => $emit('assign', { task: t, member: m })"
            @create="$emit('create-assign', { task: t })"
            @update:name="(v) => $emit('update:assignName', v)"
          />
        </section>
      </div>
    </template>
  </aside>
</template>

<script setup>
import BoardCard from './BoardCard.vue'
import { dotClass, filters, isBlocked, isFresh, statusOf } from './constants.js'

defineProps({
  scope: { type: String, default: 'team' },
  liveFull: Boolean,
  filter: { type: String, default: 'all' },
  projectName: { type: String, default: '' },
  hasProject: Boolean,
  summary: { type: String, default: '' },
  meName: { type: String, default: 'alice' },
  overview: { type: Array, default: () => [] },
  visibleTasks: { type: Array, default: () => [] },
  visibleColumns: { type: Array, default: () => [] },
  myGroups: { type: Array, default: () => [] },
  members: { type: Array, default: () => [] },
  assignFor: { type: Number, default: 0 },
  assignName: { type: String, default: '' },
})
defineEmits(['update:liveFull', 'update:filter', 'update:assignName',
             'open-project', 'toggle-assign', 'assign', 'create-assign'])
</script>
