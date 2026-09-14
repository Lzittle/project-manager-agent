<template>
  <div class="app">
    <TopBar v-if="route.name !== 'workspace'" />
    <main class="app-main" :class="{ 'app-main-flush': route.name === 'workspace' }">
      <div class="page" :class="'w-' + (route.name || 'home')">
        <router-view v-slot="{ Component }">
          <transition name="panel" mode="out-in">
            <component :is="Component" :key="route.path" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import TopBar from './components/TopBar.vue'

const route = useRoute()
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; }

.app { height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

.app-main { flex: 1; overflow-y: auto; overflow-x: hidden; }
/* 工作台 v2 自己管布局与滚动：顶栏与内边距都交给页面本身 */
.app-main-flush { overflow: hidden; }

/* 内容容器：路由名称决定宽度（对话窄栏更聚焦，数据视图放宽） */
.page {
  margin: 0 auto;
  padding: 26px 28px 56px;
  width: 100%;
  animation: squad-rise 0.25s var(--squad-ease) both;
}
.w-home { max-width: 940px; }
.w-overview { max-width: 1180px; }
.w-board { max-width: 1240px; }
.w-knowledge { max-width: 1120px; }
.w-chat { max-width: 940px; }
.w-workspace { max-width: none; padding: 0; height: 100%; animation: none; }

/* 面板级切页动效：轻抬 + 极淡滑动 */
.panel-enter-active, .panel-leave-active { transition: opacity 0.16s ease, transform 0.16s var(--squad-ease); }
.panel-enter-from { opacity: 0; transform: translateY(8px); }
.panel-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 720px) {
  .page { padding: 18px 14px 40px; }
}
</style>
