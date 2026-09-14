<template>
  <header class="topbar">
    <div class="tb-left">
      <router-link to="/" class="brand" title="回到工作台">
        <svg viewBox="0 0 32 32" class="brand-mark" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#0f766e" />
          <circle cx="12" cy="13" r="4" fill="#fff" />
          <circle cx="21" cy="13" r="4" fill="#7dd8cf" />
          <path d="M8 24c1-4 2.5-6 4-6s3 2 4 6" fill="#fff" />
          <path d="M17 24c1-4 2.5-6 4-6s3 2 4 6" fill="#7dd8cf" />
        </svg>
        <span class="brand-text">
          <span class="brand-name">Squad</span>
          <span class="brand-sub">小队智脑</span>
        </span>
      </router-link>

      <div class="tb-sep" />

      <router-link to="/" class="workbench" :class="{ active: isHome }">
        <el-icon><HomeFilled /></el-icon>
        <span>工作台</span>
      </router-link>
    </div>

    <div class="tb-right">
      <div class="ctx" v-if="store.projects.length">
        <span class="ctx-label">在做</span>
        <el-select
          v-model="store.currentId"
          class="ctx-select"
          :placeholder="'选择项目'"
          @change="onContextChange"
        >
          <el-option :value="NO_PROJECT">
            <div class="opt-global">
              <el-icon><Aim /></el-icon>
              <span>全局 · 不绑定项目</span>
            </div>
          </el-option>
          <el-option
            v-for="row in store.treeRows"
            :key="row.id"
            :value="row.id"
          >
            <span :class="{ 'opt-child': row.depth > 1 }">
              {{ indentOf(row) }}{{ row.name }}
            </span>
          </el-option>
        </el-select>
      </div>
      <div v-else class="ctx ctx-empty">还没有项目，去工作台说一句就能建</div>

      <div class="tb-sep" />

      <div class="user" title="演示用户">
        <span class="user-avatar">a</span>
        <span class="user-name">alice</span>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { HomeFilled, Aim } from '@element-plus/icons-vue'
import { useProjectStore, NO_PROJECT } from '../stores/project'

const store = useProjectStore()
const route = useRoute()

const isHome = computed(() => route.path === '/')

const indentOf = (row) => (row.depth > 1 ? '　'.repeat(row.depth - 1) + '└ ' : '')

function onContextChange() {
  // 上下文切换由各页面 watch store.currentId 自行响应（看板/记忆 reload，工作台换对话上下文）
}

onMounted(async () => {
  if (!store.projects.length) await store.load()
})
</script>

<style scoped>
.topbar {
  height: 60px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.tb-left, .tb-right { display: flex; align-items: center; gap: 14px; min-width: 0; }
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; }
.brand-mark { width: 30px; height: 30px; border-radius: 8px; box-shadow: var(--el-box-shadow-lighter); }
.brand-text { line-height: 1.1; }
.brand-name { font-size: 18px; font-weight: 800; color: var(--el-text-color-primary); letter-spacing: 0.2px; display: block; }
.brand-sub { font-size: 10px; color: var(--el-text-color-placeholder); letter-spacing: 2px; }
.tb-sep { width: 1px; height: 22px; background: var(--el-border-color-lighter); }

.workbench {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  text-decoration: none;
  transition: background 0.15s var(--squad-ease), color 0.15s var(--squad-ease);
}
.workbench:hover { background: var(--el-fill-color); color: var(--el-text-color-primary); }
.workbench.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary-dark-2); }

.ctx { display: flex; align-items: center; gap: 8px; }
.ctx-label { font-size: 12px; color: var(--el-text-color-placeholder); }
.ctx-select { width: 220px; }
.opt-global { display: inline-flex; align-items: center; gap: 6px; color: var(--el-text-color-regular); }
.opt-global .el-icon { color: var(--el-color-primary); }
.opt-child { color: var(--el-text-color-regular); }
.ctx-empty { font-size: 13px; color: var(--el-text-color-placeholder); }

.user { display: flex; align-items: center; gap: 8px; }
.user-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--el-color-primary); color: #fff;
  font-size: 13px; font-weight: 700; text-transform: uppercase;
}
.user-name { font-size: 13px; color: var(--el-text-color-regular); }

@media (max-width: 720px) {
  .brand-sub, .user-name, .ctx-label { display: none; }
  .ctx-select { width: 170px; }
}
</style>
