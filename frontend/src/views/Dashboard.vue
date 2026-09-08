<template>
  <div v-loading="loading">
    <!-- 刷新 -->
    <div class="top-bar">
      <el-button text :icon="Refresh" @click="loadAll">刷新数据</el-button>
    </div>

    <!-- 统计卡 -->
    <el-row :gutter="16" class="cards">
      <el-col v-for="card in cards" :key="card.label" :span="4">
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

    <!-- 图表区：状态分布环形图 + 项目进度概览 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :xs="24" :sm="24" :md="10">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>任务状态分布</span>
              <span class="card-sub">按任务完成阶段统计</span>
            </div>
          </template>
          <div v-if="stats.total" ref="donutEl" class="donut" />
          <el-empty v-else description="暂无任务数据" :image-size="60" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="24" :md="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>项目概览</span>
              <span class="card-sub">点击行进入看板</span>
            </div>
          </template>
          <el-table :data="projects" size="small" @row-click="goBoard">
            <el-table-column prop="name" label="项目" min-width="130" />
            <el-table-column label="生命周期" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'active' ? 'primary' : 'info'" effect="plain">
                  {{ row.status === 'active' ? '进行中' : '已归档' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="任务进度" width="150">
              <template #default="{ row }">
                <div class="prog-cell">
                  <div class="prog-row">
                    <el-progress
                      :percentage="row.pct ?? 0"
                      :stroke-width="8"
                      :show-text="false"
                      style="flex: 1"
                      :color="row.completion === 'done' ? '#22c55e' : '#4f46e5'"
                    />
                    <span class="prog-count">{{ row.done_count ?? 0 }}/{{ row.task_count ?? 0 }}</span>
                  </div>
                  <el-tag size="small" :type="completionTag(row)" class="prog-tag">{{ completionText(row) }}</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { Briefcase, Tickets, Loading, CircleCheck, FolderOpened, Clock, Refresh } from '@element-plus/icons-vue'
import { projectApi, taskApi } from '../api'
import { useProjectStore } from '../stores/project'

const router = useRouter()
const store = useProjectStore()
const loading = ref(true)
const projects = ref([])

const stats = ref({ total: 0, todo: 0, doing: 0, done: 0 })

async function loadAll() {
  loading.value = true
  try {
    projects.value = await projectApi.list()
    let total = 0, todo = 0, doing = 0, done = 0
    for (const p of projects.value) {
      const tasks = await taskApi.list(p.id)
      const d = tasks.filter((t) => t.status === 'done').length
      // 派生完成度：有任务且全部完成 -> done；有任务未完成 -> doing；无任务 -> none
      p.task_count = tasks.length
      p.done_count = d
      p.pct = tasks.length ? Math.round((d / tasks.length) * 100) : 0
      p.completion = !tasks.length ? 'none' : (d === tasks.length ? 'done' : 'doing')
      for (const t of tasks) {
        total++
        if (t.status === 'todo') todo++
        else if (t.status === 'doing') doing++
        else if (t.status === 'done') done++
      }
    }
    stats.value = { total, todo, doing, done }
    await store.load()
    renderDonut()
  } catch (e) {
    ElMessage.error('数据加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

const doneProjectCount = computed(
  () => projects.value.filter((p) => p.completion === 'done').length,
)

const cards = computed(() => [
  { label: '项目总数', value: projects.value.length, icon: Briefcase, bg: '#4f46e5' },
  { label: '任务总数', value: stats.value.total, icon: Tickets, bg: '#7c3aed' },
  { label: '待办任务', value: stats.value.todo, icon: Clock, bg: '#909399' },
  { label: '进行中任务', value: stats.value.doing, icon: Loading, bg: '#e6a23c' },
  { label: '已完成任务', value: stats.value.done, icon: CircleCheck, bg: '#22c55e' },
  { label: '已完成项目', value: doneProjectCount.value, icon: FolderOpened, bg: '#06b6d4' },
])

// ---------- ECharts 状态分布环形图 ----------
const donutEl = ref(null)
let donutChart = null

function renderDonut() {
  if (!donutEl.value) return
  if (!donutChart) {
    donutChart = echarts.init(donutEl.value)
  }
  const { total, todo, doing, done } = stats.value
  donutChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}：{c} 项（{d}%）',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#303133', fontSize: 13 },
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#606266', fontSize: 12 },
    },
    title: {
      text: String(total),
      subtext: '任务总数',
      left: 'center',
      top: '36%',
      textStyle: { fontSize: 30, fontWeight: 700, color: '#303133' },
      subtextStyle: { fontSize: 12, color: '#909399' },
    },
    series: [
      {
        type: 'pie',
        radius: ['52%', '74%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 15, fontWeight: 700, color: '#303133' },
        },
        data: [
          { value: todo, name: '待办', itemStyle: { color: '#9ca3af' } },
          { value: doing, name: '进行中', itemStyle: { color: '#4f46e5' } },
          { value: done, name: '已完成', itemStyle: { color: '#22c55e' } },
        ],
      },
    ],
  }, true)
}

function onResize() {
  donutChart?.resize()
}

onMounted(() => {
  loadAll()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  donutChart?.dispose()
  donutChart = null
})

// 完成度标签：已归档 > 已完成 > 进行中/未开始（生命周期与完成度分开表达）
const completionText = (row) => {
  if (row.status === 'archived') return '已归档'
  if (row.completion === 'done') return '已完成'
  return row.completion === 'none' ? '未开始' : '进行中'
}
const completionTag = (row) => {
  if (row.status === 'archived') return 'info'
  if (row.completion === 'done') return 'success'
  return row.completion === 'none' ? 'info' : 'primary'
}

function goBoard(row) {
  store.setCurrent(row.id)
  router.push('/board')
}
</script>

<style scoped>
.top-bar { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.card-head { display: flex; align-items: baseline; gap: 8px; }
.card-sub { font-size: 12px; color: #c0c4cc; font-weight: 400; }
.donut { height: 300px; }
.stat-card { border-radius: 12px; transition: transform 0.2s, box-shadow 0.2s; }
.stat-card:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(79, 70, 229, 0.12); }
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
.stat-num { font-size: 26px; font-weight: 700; color: #1f2329; line-height: 1.2; }
.stat-label { color: #909399; font-size: 13px; }
.prog-cell { display: flex; flex-direction: column; gap: 4px; }
.prog-row { display: flex; align-items: center; gap: 8px; }
.prog-count { font-size: 12px; color: #909399; white-space: nowrap; }
.prog-tag { align-self: flex-start; }
</style>
