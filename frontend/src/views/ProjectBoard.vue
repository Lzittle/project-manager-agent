<template>
  <div>
    <!-- 层级面包屑：根项目 → … → 当前项目（子项目可逐级进入） -->
    <div v-if="ancestors.length || store.current" class="crumb-bar">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item
          v-for="a in ancestors"
          :key="a.id"
        >
          <a class="crumb-link" @click.prevent="jumpTo(a.id)">{{ a.name }}</a>
        </el-breadcrumb-item>
        <el-breadcrumb-item v-if="store.current">
          <span class="crumb-now">{{ store.current.name }}</span>
        </el-breadcrumb-item>
      </el-breadcrumb>
      <el-tag v-if="store.currentDepth > 1" size="small" type="warning" effect="light" round>
        子项目 · 第 {{ store.currentDepth }} 级
      </el-tag>
    </div>

    <!-- 顶部操作区 -->
    <div class="toolbar">
      <el-select
        v-model="store.currentId"
        placeholder="选择项目"
        style="width: 280px"
        @change="loadTasks"
      >
        <el-option v-for="row in store.treeRows" :key="row.id" :value="row.id">
          <span :class="{ 'opt-child': row.depth > 1 }">{{ indentOf(row) }}{{ row.name }}</span>
        </el-option>
      </el-select>

      <el-button type="primary" :icon="Plus" @click="openCreateTask" :disabled="!store.current">
        新建任务
      </el-button>
      <el-tooltip content="在当前项目下创建子项目/小项目" placement="top">
        <el-button :icon="FolderAdd" @click="openCreateSubproject" :disabled="!store.current">
          建子项目
        </el-button>
      </el-tooltip>
      <el-button :icon="FolderOpened" @click="openCreateProject">新建项目</el-button>
      <span v-if="store.current" class="proj-desc">{{ store.current.description }}</span>
    </div>

    <!-- 看板三栏 -->
    <div v-loading="loading" class="board">
      <div
        v-for="col in columns"
        :key="col.status"
        class="board-col"
        :class="{ 'drop-over': dragOver === col.status }"
        @dragover.prevent="dragOver = col.status"
        @dragleave="dragOver = null"
        @drop="onDrop($event, col.status)"
      >
        <div class="col-head">
          <i class="col-dot" :style="{ background: col.color }" />
          <span class="col-title">{{ col.label }}</span>
          <span class="col-count">{{ tasksBy(col.status).length }}</span>
          <span v-if="tasks.length" class="col-share">{{ shareOf(col.status) }}%</span>
        </div>
        <div class="col-strip">
          <i :style="{ width: tasks.length ? shareOf(col.status) + '%' : '0%', background: col.color }" />
        </div>
        <div class="col-body">
          <TaskCard
            v-for="t in tasksBy(col.status)"
            :key="t.id"
            :task="t"
            @remove="removeTask"
          />
          <el-empty v-if="!tasksBy(col.status).length" description="拖拽任务到这里" :image-size="50" />
        </div>
      </div>
    </div>

    <!-- 新建任务 dialog -->
    <el-dialog v-model="taskDlg.visible" title="新建任务" width="460px">
      <el-form label-width="70px">
        <el-form-item label="任务标题" required>
          <el-input v-model="taskDlg.title" placeholder="例如：对接前端看板" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="taskDlg.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-radio-group v-model="taskDlg.priority">
            <el-radio-button value="high">高</el-radio-button>
            <el-radio-button value="medium">中</el-radio-button>
            <el-radio-button value="low">低</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="taskDlg.visible = false">取消</el-button>
        <el-button type="primary" @click="submitTask" :loading="taskDlg.submitting">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建项目 dialog（parentId 非空 = 建当前项目下的子项目） -->
    <el-dialog v-model="projDlg.visible"
               :title="projDlg.parentId ? '新建子项目（挂到当前项目下）' : '新建项目'" width="460px">
      <el-form label-width="70px">
        <el-form-item v-if="projDlg.parentId" label="父项目">
          <el-input :model-value="store.current?.name" disabled />
        </el-form-item>
        <el-form-item label="项目名称" required>
          <el-input v-model="projDlg.name" :placeholder="projDlg.parentId ? '例如：登录模块（小项目）' : '例如：电商系统'" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="projDlg.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item v-if="projDlg.parentId" label="说明">
          <div class="dlg-tip">子项目是父项目下的独立小项目：有自己的任务看板与知识库，删除父项目时整棵子树一并清理。</div>
        </el-form-item>
        <el-form-item v-if="!projDlg.parentId" label="AI 规划">
          <el-switch
            v-model="projDlg.autoPlan"
            active-text="创建后由 AI 自动规划任务（推荐）"
            inline-prompt
          />
          <div class="dlg-tip">勾选后 Agent 会按项目主题自动生成约 5 条任务（默认待办），可在看板拖拽流转</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projDlg.visible = false">取消</el-button>
        <el-button type="primary" @click="submitProject" :loading="projDlg.submitting">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, FolderAdd, FolderOpened } from '@element-plus/icons-vue'
import { taskApi, projectApi } from '../api'
import { useProjectStore } from '../stores/project'
import TaskCard from '../components/TaskCard.vue'

const store = useProjectStore()
const loading = ref(false)
const dragOver = ref(null)
const tasks = ref([])

// 列色走 v5 令牌（不再是 v3 的靛蓝/亮绿硬编码）：待办=中性点、进行中=石青、已完成=墨绿
const columns = [
  { status: 'todo', label: '待办', color: 'var(--p-idle)' },
  { status: 'doing', label: '进行中', color: 'var(--p-brand)' },
  { status: 'done', label: '已完成', color: 'var(--p-ok)' },
]

const taskDlg = reactive({ visible: false, title: '', description: '', priority: 'medium', submitting: false })
const projDlg = reactive({ visible: false, parentId: null, name: '', description: '', autoPlan: true, submitting: false })

const tasksBy = (status) => tasks.value.filter((t) => t.status === status)
// 该状态任务占总数比例（列头叙事：一眼看出负载分布）
const shareOf = (status) => (tasks.value.length
  ? Math.round((tasksBy(status).length / tasks.value.length) * 100)
  : 0)

// ---------- 层级辅助 ----------
// 树形下拉的缩进标签（子项目前加“└”并缩进）
const indentOf = (row) => (row.depth > 1 ? '\u3000'.repeat(row.depth - 1) + '└ ' : '')

// 当前项目的祖先链（根在前），面包屑用
const ancestors = computed(() => {
  const chain = []
  const seen = new Set()
  let cur = store.current
  while (cur && cur.parent_id && !seen.has(cur.id)) {
    seen.add(cur.id)
    const parent = store.projects.find((p) => p.id === cur.parent_id)
    if (!parent) break
    chain.unshift(parent)
    cur = parent
  }
  return chain
})

function jumpTo(projectId) {
  store.setCurrent(projectId)
  loadTasks()
}

async function loadTasks() {
  if (!store.currentId) { tasks.value = []; return }
  loading.value = true
  try {
    tasks.value = await taskApi.list(store.currentId)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

// ---------- 拖拽改状态（乐观更新 + PATCH） ----------
async function onDrop(e, targetStatus) {
  e.preventDefault()
  dragOver.value = null
  const id = Number(e.dataTransfer?.getData?.('text/task-id'))
  if (!id) return
  const task = tasks.value.find((t) => t.id === id)
  if (!task || task.status === targetStatus) return
  const old = task.status
  task.status = targetStatus // 乐观更新
  try {
    await taskApi.update(id, { status: targetStatus })
    ElMessage.success(`任务 #${id} 已移至「${columns.find((c) => c.status === targetStatus).label}」`)
  } catch (e) {
    task.status = old // 回滚
    ElMessage.error(e.message)
  }
}

async function removeTask(task) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${task.title}」？`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await taskApi.remove(task.id)
    tasks.value = tasks.value.filter((t) => t.id !== task.id)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 新建 ----------
function openCreateTask() { taskDlg.visible = true; taskDlg.title = ''; taskDlg.description = ''; taskDlg.priority = 'medium' }
async function submitTask() {
  if (!taskDlg.title.trim()) return ElMessage.warning('请输入任务标题')
  taskDlg.submitting = true
  try {
    await taskApi.create({
      project_id: store.currentId,
      title: taskDlg.title.trim(),
      description: taskDlg.description,
      priority: taskDlg.priority,
    })
    taskDlg.visible = false
    ElMessage.success('任务已创建')
    await loadTasks()
  } catch (e) { ElMessage.error(e.message) }
  finally { taskDlg.submitting = false }
}

function openCreateProject() {
  projDlg.visible = true
  projDlg.parentId = null
  projDlg.name = ''
  projDlg.description = ''
  projDlg.autoPlan = true
}

function openCreateSubproject() {
  if (!store.current) return
  projDlg.visible = true
  projDlg.parentId = store.currentId
  projDlg.name = ''
  projDlg.description = ''
  projDlg.autoPlan = false // 子项目默认不自动规划，任务由用户/父项目阶段拆分
}

async function submitProject() {
  if (!projDlg.name.trim()) return ElMessage.warning('请输入项目名称')
  projDlg.submitting = true
  try {
    const parentId = projDlg.parentId
    const list = (await store.create(projDlg.name.trim(), projDlg.description, parentId)) || []
    const name = projDlg.name.trim()
    // 优先按「同名 + 挂在同一父级下」定位刚建的项目（避免同名项目撞车取错）
    const created = list.find((p) => p.name === name && (p.parent_id ?? null) === parentId)
    const pid = created?.id ?? list.find((p) => p.name === name)?.id ?? list[0]?.id ?? store.currentId
    store.setCurrent(pid)
    // 顶层项目勾选「一键规划」：创建后立刻让 AI 按主题生成任务；子项目不自动规划
    if (!parentId && projDlg.autoPlan && pid != null) {
      loading.value = true
      try {
        const res = await projectApi.plan(pid)
        ElMessage.success(`AI 已自动规划 ${res.planned} 个任务（默认待办，可拖拽流转）`)
      } catch (planErr) {
        // 项目已创建成功；规划失败不影响使用，提示走对话页可重试
        ElMessage.warning(`项目已创建，但 AI 规划失败：${planErr.message}。可去「AI 对话」页重新规划`)
      } finally {
        loading.value = false
      }
    } else if (parentId) {
      ElMessage.success(`子项目已创建，挂到「${store.current?.name ?? ''}」下`)
    } else {
      ElMessage.success('项目已创建')
    }
    projDlg.visible = false
    await loadTasks()
  } catch (e) { ElMessage.error(e.message) }
  finally { projDlg.submitting = false }
}

onMounted(async () => {
  if (!store.projects.length) await store.load()
  await loadTasks()
})
</script>

<style scoped>
/* v5 令牌（D-013）：列 = 8 圆角「卡片」；拖拽高亮走石青软底（不再用浅靛蓝 #eef1ff 硬编码） */
.crumb-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-radius: var(--p-r-sm);
}
.crumb-link { color: var(--p-brand); cursor: pointer; font-weight: 500; }
.crumb-now { color: var(--p-ink); font-weight: 600; }
.opt-child { color: var(--p-ink-2); font-size: var(--p-fs-ui); }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.proj-desc { color: var(--p-ink-2); font-size: var(--p-fs-ui); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.board { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; align-items: start; }
.board-col {
  background: var(--p-line-soft);
  border: 1px solid var(--p-line);
  border-radius: var(--p-r-sm);
  padding: 14px;
  min-height: 320px;
  transition: background 0.2s var(--squad-ease), border-color 0.2s var(--squad-ease);
}
.board-col.drop-over { background: var(--p-brand-wash); border-color: var(--p-brand-line); }
.col-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; }
.col-dot { width: 8px; height: 8px; border-radius: 50%; align-self: center; }
.col-title { font-weight: 600; color: var(--p-ink); font-size: var(--p-fs-title); }
.col-count {
  font-size: var(--p-fs-meta); font-weight: 600; color: var(--p-ink-2);
  font-variant-numeric: tabular-nums;
}
.col-share { font-size: var(--p-fs-meta); color: var(--p-idle); margin-left: auto; font-variant-numeric: tabular-nums; }
.col-strip {
  height: 3px; border-radius: var(--p-r-pill); background: var(--p-line);
  overflow: hidden; margin-bottom: 12px;
}
.col-strip i { display: block; height: 100%; border-radius: var(--p-r-pill); opacity: 0.85; transition: width 0.3s var(--squad-ease); }
.col-body { min-height: 200px; }
.dlg-tip { color: var(--p-ink-2); font-size: var(--p-fs-tag); line-height: var(--p-lh-ui); margin-top: 4px; }
</style>
