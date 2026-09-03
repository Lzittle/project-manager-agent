<template>
  <div v-loading="loading">
    <!-- 统计卡 -->
    <el-row :gutter="16" class="cards">
      <el-col v-for="card in cards" :key="card.label" :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon" :style="{ background: card.bg }">
            <el-icon :size="26" color="#fff"><component :is="card.icon" /></el-icon>
          </div>
          <div>
            <div class="stat-num">{{ card.value }}</div>
            <div class="stat-label">{{ card.label }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 状态分布 + 项目列表 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>任务状态分布</template>
          <div v-if="stats.total" class="dist">
            <div v-for="s in dist" :key="s.status" class="dist-row">
              <span class="dist-label">{{ s.label }}</span>
              <el-progress
                :percentage="Math.round((s.count / stats.total) * 100)"
                :color="s.color"
                :stroke-width="14"
                :show-text="false"
                style="flex: 1"
              />
              <span class="dist-count">{{ s.count }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无任务数据" :image-size="60" />
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>项目概览</template>
          <el-table :data="projects" size="small" @row-click="goBoard">
            <el-table-column prop="name" label="项目" min-width="140" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status === 'active' ? '进行中' : '已归档' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="任务数" width="90" align="center">
              <template #default="{ row }">{{ row.task_count ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Briefcase, Tickets, Loading, CircleCheck, FolderOpened } from '@element-plus/icons-vue'
import { projectApi, taskApi, knowledgeApi } from '../api'
import { useProjectStore } from '../stores/project'

const router = useRouter()
const store = useProjectStore()
const loading = ref(true)
const projects = ref([])
const docCount = ref(0)

const stats = ref({ total: 0, todo: 0, doing: 0, done: 0 })

async function loadAll() {
  loading.value = true
  try {
    projects.value = await projectApi.list()
    let total = 0, todo = 0, doing = 0, done = 0, docs = 0
    for (const p of projects.value) {
      const tasks = await taskApi.list(p.id)
      p.task_count = tasks.length
      for (const t of tasks) {
        total++
        if (t.status === 'todo') todo++
        else if (t.status === 'doing') doing++
        else if (t.status === 'done') done++
      }
      try { docs += (await knowledgeApi.list(p.id)).length } catch { /* 忽略 */ }
    }
    stats.value = { total, todo, doing, done }
    docCount.value = docs
    await store.load()
  } catch (e) {
    ElMessage.error('数据加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

const cards = computed(() => [
  { label: '项目总数', value: projects.value.length, icon: Briefcase, bg: '#409eff' },
  { label: '任务总数', value: stats.value.total, icon: Tickets, bg: '#9254de' },
  { label: '进行中', value: stats.value.doing, icon: Loading, bg: '#e6a23c' },
  { label: '已完成', value: stats.value.done, icon: CircleCheck, bg: '#67c23a' },
])

const dist = computed(() => [
  { status: 'todo', label: '待办', count: stats.value.todo, color: '#909399' },
  { status: 'doing', label: '进行中', count: stats.value.doing, color: '#409eff' },
  { status: 'done', label: '已完成', count: stats.value.done, color: '#67c23a' },
])

function goBoard(row) {
  store.setCurrent(row.id)
  router.push('/board')
}

onMounted(loadAll)
</script>

<style scoped>
.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon {
  width: 52px; height: 52px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.stat-num { font-size: 26px; font-weight: 700; color: #303133; line-height: 1.2; }
.stat-label { color: #909399; font-size: 13px; }
.dist-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.dist-label { width: 56px; color: #606266; font-size: 13px; }
.dist-count { width: 32px; text-align: right; font-weight: 600; color: #303133; }
</style>
