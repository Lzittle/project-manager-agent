<template>
  <el-container class="layout">
    <Sidebar />

    <el-container>
      <el-header class="header">
        <div class="header-title">{{ $route.meta.title || '项目管理' }}</div>
        <el-tag type="success" effect="light" round>
          <el-icon style="vertical-align: -2px; margin-right: 4px"><User /></el-icon>
          alice (演示用户)
        </el-tag>
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
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-title { font-size: 18px; font-weight: 600; }
.main { background: #f5f7fa; }
</style>
