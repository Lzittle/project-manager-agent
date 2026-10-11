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

      <!-- 身份（轮 3）：未登录是演示身份 alice；点开可登录 / 注册 / 邀请码认领 / 退出 -->
      <IdentityMenu>
        <template #trigger>
          <span class="user-avatar">{{ auth.displayName.slice(0, 1).toUpperCase() }}</span>
          <span class="user-name">{{ auth.displayName }}</span>
        </template>
      </IdentityMenu>
    </div>
  </header>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { HomeFilled, Aim } from '@element-plus/icons-vue'
import { useProjectStore, NO_PROJECT } from '../stores/project'
import { useAuthStore } from '../stores/auth'
import IdentityMenu from './IdentityMenu.vue'

const store = useProjectStore()
const auth = useAuthStore()
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
/* v5 令牌（D-013）：暖中性灰阶 + 石青主色；圆角走 4/8/16/999；字号走 --p-fs-*（rem，跟顶栏「Aa」缩放） */
.topbar {
  height: 60px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1.25rem;
  background: color-mix(in srgb, var(--p-surface) 92%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--p-line);
}
.tb-left, .tb-right { display: flex; align-items: center; gap: 0.875rem; min-width: 0; }
.brand { display: flex; align-items: center; gap: 0.625rem; text-decoration: none; }
.brand-mark { width: 30px; height: 30px; border-radius: var(--p-r-sm); }
.brand-text { line-height: 1.1; }
.brand-name { font-size: 1.125rem; font-weight: 800; color: var(--p-ink); letter-spacing: 0.2px; display: block; }
.brand-sub { font-size: var(--p-fs-eyebrow); color: var(--p-idle); letter-spacing: 2px; }
.tb-sep { width: 1px; height: 22px; background: var(--p-line); }

.workbench {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: var(--p-ctl-h);          /* 与右侧项目选择器同高，横向一条线 */
  padding: 0 0.875rem;
  border-radius: var(--p-r-sm);
  font-size: var(--p-fs-ui);
  font-weight: 600;
  color: var(--p-ink-2);
  text-decoration: none;
  transition: background var(--p-dur-fast) var(--squad-ease), color var(--p-dur-fast) var(--squad-ease);
}
.workbench:hover { background: var(--p-line-soft); color: var(--p-ink); }
.workbench.active { background: var(--p-brand-wash); color: var(--p-brand-strong); }

.ctx { display: flex; align-items: center; gap: 0.5rem; }
.ctx-label { font-size: var(--p-fs-meta); color: var(--p-idle); }
.ctx-select { width: 220px; }
.opt-global { display: inline-flex; align-items: center; gap: 6px; color: var(--p-ink-2); }
.opt-global .el-icon { color: var(--p-brand); }
.opt-child { color: var(--p-ink-2); }
.ctx-empty { font-size: var(--p-fs-ui); color: var(--p-idle); }

.user-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--p-brand); color: #fff;
  font-size: var(--p-fs-ui); font-weight: 700; text-transform: uppercase;
}
.user-name { font-size: var(--p-fs-ui); color: var(--p-ink-2); }

@media (max-width: 720px) {
  .brand-sub, .user-name, .ctx-label { display: none; }
  .ctx-select { width: 170px; }
}
</style>
