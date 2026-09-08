<template>
  <el-aside width="224px" class="sidebar">
    <div class="brand">
      <div class="brand-logo">
        <!-- Squad：四格小队图标 -->
        <svg viewBox="0 0 32 32" width="26" height="26">
          <rect width="32" height="32" rx="8" fill="#fff" opacity="0.14" />
          <circle cx="11.5" cy="12.5" r="3.6" fill="#fff" />
          <circle cx="20.5" cy="12.5" r="3.6" fill="#c7d2fe" />
          <path d="M7.5 23c0.8-3.6 2.3-5.4 4-5.4s3.2 1.8 4 5.4" fill="#fff" />
          <path d="M16.5 23c0.8-3.6 2.3-5.4 4-5.4s3.2 1.8 4 5.4" fill="#c7d2fe" />
        </svg>
      </div>
      <div class="brand-text">
        <div class="brand-name">Squad</div>
        <div class="brand-sub">小队智脑</div>
      </div>
    </div>

    <div class="nav-title">工作台</div>
    <el-menu :default-active="active" router class="menu">
      <el-menu-item index="/">
        <el-icon><Odometer /></el-icon><span>数据仪表盘</span>
      </el-menu-item>
      <el-menu-item index="/board">
        <el-icon><Tickets /></el-icon><span>项目看板</span>
      </el-menu-item>
      <el-menu-item index="/chat">
        <el-icon><ChatDotRound /></el-icon><span>AI 对话</span>
      </el-menu-item>
      <el-menu-item index="/knowledge">
        <el-icon><Document /></el-icon><span>知识库 · 记忆</span>
      </el-menu-item>
    </el-menu>

    <div class="sidebar-foot">
      <div class="foot-line" />
      <div class="foot-tip">研究型端到端 Agent 系统</div>
    </div>
  </el-aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Odometer, Tickets, ChatDotRound, Document } from '@element-plus/icons-vue'

const route = useRoute()
const active = computed(() => route.path)
</script>

<style scoped>
.sidebar {
  background: linear-gradient(180deg, var(--squad-sidebar-bg-2) 0%, var(--squad-sidebar-bg) 100%);
  display: flex;
  flex-direction: column;
  color: var(--squad-sidebar-text);
  border-right: none;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 14px;
}
.brand-logo { display: flex; }
.brand-text { line-height: 1.15; }
.brand-name {
  font-size: 19px;
  font-weight: 800;
  color: #fff;
  letter-spacing: 0.5px;
}
.brand-sub { font-size: 11px; color: var(--squad-sidebar-text); letter-spacing: 2px; }
.nav-title {
  font-size: 11px;
  color: var(--squad-sidebar-text);
  opacity: 0.6;
  padding: 8px 18px 6px;
  letter-spacing: 1px;
}
.menu {
  border-right: none;
  background: transparent;
  flex: 1;
  padding: 0 10px;
}
.menu :deep(.el-menu-item) {
  color: var(--squad-sidebar-text);
  border-radius: 8px;
  margin-bottom: 4px;
  height: 44px;
}
.menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.9), rgba(79, 70, 229, 0.75));
  color: #fff;
  font-weight: 600;
}
.sidebar-foot { padding: 14px 18px 16px; }
.foot-line { height: 1px; background: rgba(255, 255, 255, 0.12); margin-bottom: 10px; }
.foot-tip { font-size: 10px; color: var(--squad-sidebar-text); opacity: 0.5; }
</style>
