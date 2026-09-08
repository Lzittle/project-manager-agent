<template>
  <el-container class="layout">
    <Sidebar />

    <el-container class="right">
      <el-header class="header">
        <div class="header-title">
          {{ $route.meta.title || 'Squad' }}
          <span v-if="$route.meta.title" class="header-crumb">/ Squad · 小队智脑</span>
        </div>
        <div class="header-right">
          <el-tag type="primary" effect="plain" round>
            <el-icon style="vertical-align: -2px; margin-right: 4px"><User /></el-icon>
            alice (演示用户)
          </el-tag>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { User } from '@element-plus/icons-vue'
import Sidebar from './components/Sidebar.vue'
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; }
body { font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif; }

.layout { height: 100%; }
.header {
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px !important;
  padding: 0 20px;
}
.header-title { font-size: 17px; font-weight: 700; color: var(--el-text-color-primary); }
.header-crumb { font-size: 12px; font-weight: 400; color: var(--el-text-color-placeholder); margin-left: 8px; }
.main {
  background: var(--el-bg-color-page);
  padding: 18px 20px;
  overflow-y: auto;
}
/* 页面卡片统一呼吸感（其余 token 见 theme.css 全局 .el-card） */
.el-card { border-radius: var(--squad-radius-card); }
</style>
