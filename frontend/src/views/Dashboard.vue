<template>
  <div v-loading="loading" class="dash">
    <!-- ======== 指挥舱 Hero：整体完成率叙事（真实数据） ======== -->
    <el-card shadow="never" class="hero">
      <div class="hero-grid">
        <div class="hero-left">
          <div class="hero-eyebrow">
            <span>SQUAD · 小队智脑</span>
            <el-button text size="small" :icon="Refresh" class="hero-refresh" @click="loadAll">刷新</el-button>
          </div>
          <div class="hero-title">项目健康总览</div>
          <div class="hero-num">
            <span class="hero-big">{{ overallPct }}%</span>
            <span class="hero-num-sub">整体完成率</span>
          </div>
          <div class="hero-stats">
            <div class="hs">
              <span class="hs-v"><i class="hs-dot s-done" />{{ stats.done }}</span>
              <span class="hs-k">已完成任务</span>
            </div>
            <i class="hs-div" />
            <div class="hs">
              <span class="hs-v"><i class="hs-dot s-doing" />{{ stats.doing }}</span>
              <span class="hs-k">进行中</span>
            </div>
            <i class="hs-div" />
            <div class="hs">
              <span class="hs-v"><i class="hs-dot s-blocked" />{{ stats.blocked }}</span>
              <span class="hs-k">待解锁</span>
            </div>
          </div>
        </div>
        <div class="hero-right">
          <div class="hr-head">
            <span class="hr-title">各项目进度</span>
            <span class="hr-total">{{ projectsCount }} 个项目</span>
          </div>
          <div
            v-for="r in topRails"
            :key="r.id"
            class="rail"
            role="button"
            tabindex="0"
            @click="goBoard(r)"
            @keydown.enter="goBoard(r)"
          >
            <span class="rail-dot" :class="railDot(r)" />
            <span class="rail-name">{{ r.name }}</span>
            <span class="rail-track"><i :style="{ width: (r.pct ?? 0) + '%' }" /></span>
            <span class="rail-pct">{{ r.pct ?? 0 }}%</span>
          </div>
          <div v-if="!topRails.length" class="hr-empty">暂无项目，去「项目看板」新建</div>
        </div>
      </div>
    </el-card>

    <!-- ======== 主体：项目进度轨道 + 状态分布 ======== -->
    <el-row :gutter="16" class="body-row">
      <el-col :xs="24" :md="15">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span>项目进度</span>
              <span class="panel-sub">点项目名或子项目标签进入看板</span>
            </div>
          </template>
          <div v-if="rails.length">
            <div v-for="r in rails" :key="r.id" class="proj-row" @click="goBoard(r)">
              <div class="proj-head">
                <div class="proj-title">
                  <i class="proj-dot" :class="'c-' + (r.completion || 'none')" />
                  <span class="proj-name">{{ r.name }}</span>
                  <el-tag v-if="r.status === 'archived'" size="small" type="info" effect="plain">已归档</el-tag>
                </div>
                <span class="proj-pct">{{ r.pct }}%</span>
              </div>
              <div class="proj-track"><i :style="{ width: (r.pct ?? 0) + '%' }" /></div>
              <div class="proj-meta">
                <span class="proj-counts">{{ r._agg.done }}/{{ r._agg.total }} 完成</span>
                <div class="proj-kids">
                  <el-tag
                    v-for="k in r._kids"
                    :key="k.id"
                    size="small"
                    effect="plain"
                    class="kid"
                    @click.stop="goBoard(k)"
                  >└ {{ k.name }}</el-tag>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无项目，去「项目看板」新建一个" :image-size="70" />
        </el-card>
      </el-col>
      <el-col :xs="24" :md="9">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <span>任务状态分布</span>
            </div>
          </template>
          <div v-if="stats.total" ref="donutEl" class="donut" />
          <el-empty v-else description="暂无任务" :image-size="60" />
        </el-card>
        <el-card shadow="never" class="panel" style="margin-top: 16px">
          <template #header>
            <div class="panel-head">
              <span>需关注</span>
              <span class="panel-sub">等前置任务完成后可继续</span>
            </div>
          </template>
          <div v-if="needs.length" class="needs">
            <div v-for="n in needs" :key="n.id" class="need-row" @click="goProject(n.project_id)">
              <el-icon class="need-ic" color="var(--p-on-sand)"><WarningFilled /></el-icon>
              <div class="need-body">
                <div class="need-title">{{ n.title }}</div>
                <div class="need-proj">{{ n.project_name }}</div>
              </div>
              <el-icon class="need-go" color="var(--p-idle)"><ArrowRight /></el-icon>
            </div>
          </div>
          <div v-else class="needs-empty">没有待解锁任务，一切就绪</div>
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
import { Refresh, WarningFilled, ArrowRight } from '@element-plus/icons-vue'
import { projectApi, taskApi } from '../api'
import { useProjectStore } from '../stores/project'

const router = useRouter()
const store = useProjectStore()
const loading = ref(true)
const rows = ref([])                 // 根项目行（含子树聚合 _agg + 子项目 _kids）
const stats = ref({ total: 0, todo: 0, doing: 0, done: 0, blocked: 0 })
const needs = ref([])                // 需关注：阻塞任务清单（真实数据）
const donutEl = ref(null)
let donutChart = null

async function loadAll() {
  loading.value = true
  try {
    const projects = await projectApi.list()
    const byId = new Map(projects.map((p) => [p.id, p]))
    const childrenOf = new Map()
    for (const p of projects) {
      if (p.parent_id && byId.has(p.parent_id)) {
        if (!childrenOf.has(p.parent_id)) childrenOf.set(p.parent_id, [])
        childrenOf.get(p.parent_id).push(p)
      }
    }
    // 每项目直接任务统计（含阻塞计数 + 阻塞任务明细）
    const direct = new Map()
    for (const p of projects) {
      const tasks = await taskApi.list(p.id)
      const blockedTasks = tasks
        .filter((t) => t.status !== 'done' && (t.blocked_by_count || 0) > 0)
        .map((t) => ({ id: t.id, title: t.title, project_id: p.id, project_name: p.name }))
      direct.set(p.id, {
        total: tasks.length,
        todo: tasks.filter((t) => t.status === 'todo').length,
        doing: tasks.filter((t) => t.status === 'doing').length,
        done: tasks.filter((t) => t.status === 'done').length,
        blocked: blockedTasks.length,
        blockedTasks,
      })
    }
    // 子树聚合
    const memo = new Map()
    const aggregate = (id) => {
      if (memo.has(id)) return memo.get(id)
      const acc = { ...(direct.get(id) || { total: 0, todo: 0, doing: 0, done: 0, blocked: 0, blockedTasks: [] }) }
      for (const c of childrenOf.get(id) || []) {
        const s = aggregate(c.id)
        acc.total += s.total; acc.todo += s.todo; acc.doing += s.doing
        acc.done += s.done; acc.blocked += s.blocked
        acc.blockedTasks = acc.blockedTasks.concat(s.blockedTasks)
      }
      memo.set(id, acc)
      return acc
    }
    const roots = projects
      .filter((p) => !p.parent_id || !byId.has(p.parent_id))
      .sort((a, b) => b.id - a.id)
    rows.value = roots.map((p) => {
      const agg = aggregate(p.id)
      return {
        ...p,
        _agg: agg,
        pct: agg.total ? Math.round((agg.done / agg.total) * 100) : 0,
        completion: !agg.total ? 'none' : (agg.done === agg.total ? 'done' : 'doing'),
        _kids: (childrenOf.get(p.id) || []).sort((a, b) => b.id - a.id),
      }
    })
    let total = 0, todo = 0, doing = 0, done = 0, blocked = 0
    for (const r of rows.value) {
      total += r._agg.total; todo += r._agg.todo; doing += r._agg.doing
      done += r._agg.done; blocked += r._agg.blocked
    }
    stats.value = { total, todo, doing, done, blocked }
    // 需关注：全子树阻塞任务按 id 倒序取前 8
    needs.value = rows.value
      .flatMap((r) => r._agg.blockedTasks || [])
      .sort((a, b) => b.id - a.id)
      .slice(0, 8)
    await store.load()
    renderDonut()
  } catch (e) {
    ElMessage.error('数据加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

const projectsCount = computed(() => rows.value.length)
const overallPct = computed(() =>
  stats.value.total ? Math.round((stats.value.done / stats.value.total) * 100) : 0)
// hero 右侧 rails：未归档优先，按完成度降序取前 5
const topRails = computed(() => [...rows.value]
  .sort((a, b) => (a.status === 'archived') - (b.status === 'archived') || (b.pct ?? 0) - (a.pct ?? 0))
  .slice(0, 5))
const rails = computed(() => [...rows.value].sort((a, b) => b.pct - a.pct))
const railDot = (r) => (r.status === 'archived' ? 'dot-archived' : `dot-${r.completion || 'none'}`)

// ---------- 状态分布环形图 ----------
// 色值取 v5 令牌的字面量（ECharts 配置拿不到 CSS 变量）：
// ink #37352f · ink-2 #6b6a66 · idle #838d94 · line #e9e9e7 · brand #0f766e · ok #15794a
function renderDonut() {
  if (!donutEl.value) return
  if (!donutChart) donutChart = echarts.init(donutEl.value)
  const { total, todo, doing, done } = stats.value
  donutChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}：{c} 项（{d}%）',
      backgroundColor: '#ffffff',
      borderColor: '#e9e9e7',
      borderWidth: 1,
      textStyle: { color: '#37352f', fontSize: 13 },
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#6b6a66', fontSize: 12 },
    },
    title: {
      text: String(total),
      subtext: '任务总数',
      left: 'center',
      top: '34%',
      textStyle: { fontSize: 30, fontWeight: 600, color: '#37352f' },
      subtextStyle: { fontSize: 12, color: '#838d94' },
    },
    series: [{
      type: 'pie',
      radius: ['55%', '76%'],
      center: ['50%', '44%'],
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 15, fontWeight: 600, color: '#37352f' } },
      data: [
        { value: todo, name: '待办', itemStyle: { color: '#838d94' } },
        { value: doing, name: '进行中', itemStyle: { color: '#0f766e' } },
        { value: done, name: '已完成', itemStyle: { color: '#15794a' } },
      ],
    }],
  }, true)
}

function onResize() { donutChart?.resize() }

function goBoard(project) {
  store.setCurrent(project.id)
  router.push('/board')
}

function goProject(pid) {
  store.setCurrent(pid)
  router.push('/board')
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
</script>

<style scoped>
.dash { display: flex; flex-direction: column; gap: 16px; }

/* ---------- Hero：项目健康总览（v5 暖奶油白卡 + 石青；状态只用点，不刷彩色字） ---------- */
.hero { border: none !important; }
.hero :deep(.el-card__body) { padding: 0; }
.hero-grid {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 40px;
  padding: 26px 30px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-radius: var(--p-r-lg);
}
.hero-eyebrow {
  font-size: var(--p-fs-eyebrow);
  letter-spacing: 0.14em;
  color: var(--p-idle);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.hero-refresh { letter-spacing: 0; color: var(--p-ink-2); }
.hero-refresh:hover { color: var(--p-ink); }
.hero-title { font-size: var(--p-fs-title); font-weight: 500; color: var(--p-ink-2); margin-bottom: 18px; }
.hero-num { display: flex; align-items: baseline; gap: 12px; margin-bottom: 18px; }
.hero-big {
  font-size: 3.25rem; font-weight: 600; letter-spacing: -0.02em; line-height: 1;
  color: var(--p-ink); font-variant-numeric: tabular-nums;
}
.hero-num-sub { color: var(--p-idle); font-size: var(--p-fs-meta); }
.hero-stats { display: flex; align-items: center; gap: 20px; }
.hs { display: flex; flex-direction: column; gap: 4px; }
.hs-v {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 1.375rem; font-weight: 600; line-height: 1.1;
  color: var(--p-ink); font-variant-numeric: tabular-nums;
}
.hs-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.hs-dot.s-done { background: var(--p-ok); }
.hs-dot.s-doing { background: var(--p-brand); }
.hs-dot.s-blocked { background: var(--p-on-sand); }
.hs-k { font-size: var(--p-fs-tag); color: var(--p-idle); }
.hs-div { width: 1px; height: 26px; background: var(--p-line); }

.hero-right { align-self: center; }
.hr-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
.hr-title { font-size: var(--p-fs-ui); font-weight: 500; color: var(--p-ink-2); }
.hr-total { font-size: var(--p-fs-tag); color: var(--p-idle); }
.rail {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 8px; margin-bottom: 4px;
  border-radius: var(--p-r-sm);
  cursor: pointer;
  transition: background 0.15s var(--squad-ease);
}
.rail:hover { background: var(--p-line-soft); }
.rail-name {
  width: 120px; font-size: var(--p-fs-ui); color: var(--p-ink-2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.rail-track {
  flex: 1; height: 4px; border-radius: var(--p-r-pill);
  background: var(--p-line-soft); overflow: hidden;
}
.rail-track i {
  display: block; height: 100%; border-radius: var(--p-r-pill);
  background: var(--p-brand); transition: width 0.4s var(--squad-ease);
}
.rail-pct { width: 40px; text-align: right; font-size: var(--p-fs-meta); color: var(--p-idle); font-variant-numeric: tabular-nums; }
.rail-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-done { background: var(--p-ok); }
.dot-doing { background: var(--p-brand); }
.dot-none { background: var(--p-idle); }
.dot-archived { background: var(--p-line); }
.hr-empty { color: var(--p-idle); font-size: var(--p-fs-ui); padding: 12px 8px; }

/* ---------- 主体：项目进度「轨道」（v5 令牌） ---------- */
.panel { border-radius: var(--p-r-lg); }
.panel-head { display: flex; align-items: baseline; gap: 10px; }
.panel-sub { font-size: var(--p-fs-tag); color: var(--p-idle); font-weight: 400; }
.proj-row {
  padding: 12px 4px;
  border-bottom: 1px solid var(--p-line-soft);
  cursor: pointer;
  transition: background 0.15s var(--squad-ease);
}
.proj-row:last-child { border-bottom: none; }
.proj-row:hover { background: var(--p-line-soft); }
.proj-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.proj-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.proj-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.proj-dot.c-done { background: var(--p-ok); }
.proj-dot.c-doing { background: var(--p-brand); }
.proj-dot.c-none { background: var(--p-idle); }
.proj-name { font-weight: 500; color: var(--p-ink); font-size: var(--p-fs-body); }
.proj-pct { font-size: var(--p-fs-body); font-weight: 600; color: var(--p-ink); font-variant-numeric: tabular-nums; }
.proj-track {
  height: 6px; border-radius: var(--p-r-pill); background: var(--p-line-soft);
  overflow: hidden; margin-bottom: 8px;
}
.proj-track i {
  display: block; height: 100%; border-radius: var(--p-r-pill);
  background: var(--p-brand); transition: width 0.4s var(--squad-ease);
}
.proj-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.proj-counts { font-size: var(--p-fs-tag); color: var(--p-ink-2); font-variant-numeric: tabular-nums; }
.proj-kids { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; }
.kid { cursor: pointer; }
.kid:hover { color: var(--p-brand); }

.donut { height: 300px; }

/* ---------- 需关注（右侧行动引导） ---------- */
.needs { display: flex; flex-direction: column; max-height: 280px; overflow-y: auto; }
.need-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 6px;
  border-radius: var(--p-r-sm);
  cursor: pointer;
  transition: background 0.15s var(--squad-ease);
}
.need-row:hover { background: var(--p-line-soft); }
.need-ic { flex-shrink: 0; }
.need-body { flex: 1; min-width: 0; }
.need-title {
  font-size: var(--p-fs-ui); color: var(--p-ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.need-proj { font-size: var(--p-fs-tag); color: var(--p-idle); }
.need-go { flex-shrink: 0; }
.needs-empty {
  padding: 18px 0; text-align: center;
  color: var(--p-ok); font-size: var(--p-fs-ui);
}

@media (max-width: 992px) {
  .hero-grid { grid-template-columns: 1fr; gap: 20px; }
}
</style>
