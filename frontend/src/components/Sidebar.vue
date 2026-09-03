<template>
  <el-aside width="220px" class="sidebar">
    <div class="brand">
      <el-icon :size="22"><SetUp /></el-icon>
      <span>项目管理 Agent</span>
    </div>
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
        <el-icon><Document /></el-icon><span>知识库</span>
      </el-menu-item>
    </el-menu>
  </el-aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Odometer, Tickets, ChatDotRound, Document, SetUp } from '@element-plus/icons-vue'

const route = useRoute()
const active = computed(() => route.path)
</script>

<style scoped>
.sidebar {
  background: #fff;
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 16px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.menu { border-right: none; flex: 1; }
</style>
