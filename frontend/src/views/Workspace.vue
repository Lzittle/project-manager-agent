<template>
  <div class="ws">
    <!-- ===== 唯一的一行：范围 + 上下文 + 面板开关 ===== -->
    <header class="ws-top">
      <div class="ws-brand">
        <span class="ws-logo">S</span>
        <span class="ws-brandtext"><b>Squad</b><i>小队智脑</i></span>
      </div>

      <div class="ws-scopes" role="group" aria-label="范围">
        <button class="ws-chip" :class="{ on: scope === 'team' }" type="button" @click="setScope('team')">全队</button>
        <button class="ws-chip" :class="{ on: scope === 'me' }" type="button" @click="setScope('me')">我 · {{ meName }}</button>
      </div>

      <div class="ws-crumbs">
        <template v-if="store.current">
          <span v-for="a in ancestors" :key="a.id" class="ws-crumb">{{ a.name }}<span class="ws-sep">›</span></span>
          <span class="ws-crumbon">{{ store.current.name }}</span>
        </template>
        <span v-else class="ws-crumb">全局 · 不绑定项目</span>
        <el-select
          v-model="store.currentId"
          class="ws-pick"
          size="small"
          placeholder="选择项目"
        >
          <el-option :value="0" label="全局 · 不绑定项目" />
          <el-option v-for="row in store.treeRows" :key="row.id" :value="row.id" :label="row.name" />
        </el-select>
      </div>

      <div class="ws-panels" role="group" aria-label="侧栏开关">
        <button class="ws-chip" :class="{ on: assetsOpen }" type="button" @click="assetsOpen = !assetsOpen">资产库</button>
        <button class="ws-chip" :class="{ on: liveOpen }" type="button" @click="toggleLive">任务</button>
      </div>

      <span class="ws-avatar">{{ meName.slice(0, 1).toUpperCase() }}</span>
    </header>

    <div class="ws-main" :class="{ 'is-full': liveFull }">
      <!-- ===== 左：资产库 ===== -->
      <aside v-show="assetsOpen" class="ws-assets" aria-label="资产库">
        <div class="ws-ashead"><b>资产库</b><span>这次对话用到的</span></div>

        <div class="ws-group">规划文书</div>
        <button
          v-for="doc in repoDocs"
          :key="doc.name"
          class="ws-file"
          :class="{ on: picked && picked.kind === 'repo' && picked.name === doc.name }"
          type="button"
          @click="pickRepoDoc(doc)"
        >
          <i class="ws-mark" aria-hidden="true" />
          <span class="ws-filename">{{ doc.name }}</span>
          <span class="ws-filenote">{{ doc.note }}</span>
        </button>

        <div class="ws-group">项目记忆</div>
        <button
          v-for="doc in documents"
          :key="doc.id"
          class="ws-file"
          :class="{ on: picked && picked.kind === 'doc' && picked.id === doc.id }"
          type="button"
          @click="pickDocument(doc)"
        >
          <i class="ws-mark" aria-hidden="true" />
          <span class="ws-filename">{{ doc.title }}</span>
          <span class="ws-filenote">{{ doc.doc_type || '文档' }}</span>
        </button>
        <div v-if="!documents.length" class="ws-empty-small">
          {{ store.currentId ? '这个项目还没有记忆文档' : '先在顶部选一个项目' }}
        </div>

        <div class="ws-preview">
          <div class="ws-preview-head">{{ picked ? picked.name : '点左侧任意一项' }}</div>
          <p>{{ picked ? picked.text : '这里显示你选中的资料的摘要。' }}</p>
        </div>
      </aside>

      <!-- ===== 中：对话（居中） ===== -->
      <section class="ws-chat">
        <div class="ws-thin">
          <div ref="threadEl" class="ws-thread">
            <div v-if="!messages.length" class="ws-hello">
              <p class="ws-hello-title">我是 Squad。说一句你想推进的事，我会拆成任务放到右边的现场里。</p>
              <div class="ws-suggest">
                <button class="ws-act" type="button" @click="send('帮我规划几项任务')">帮我规划几项任务</button>
                <button class="ws-act" type="button" @click="send('现在有哪些任务？')">现在有哪些任务？</button>
              </div>
            </div>
            <ChatMessage
              v-for="(m, i) in messages"
              :key="i"
              :role="m.role"
              :content="m.content"
              :trace="m.trace"
              @goto="onGoToRef"
            />
            <div v-if="sending" class="ws-typing">正在思考并调用工具…</div>
          </div>

          <div class="ws-composer">
            <textarea
              v-model="draft"
              class="ws-input"
              rows="1"
              placeholder="说一句要干什么…（Enter 发送，Shift+Enter 换行）"
              @keydown.enter.exact.prevent="send()"
            />
            <div class="ws-sendrow">
              <span class="ws-note">对话产出的任务会直接落到右边的现场</span>
              <button class="ws-send" type="button" :disabled="sending || !draft.trim()" @click="send()">发送</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ===== 右：现场（预览 → 全屏） ===== -->
      <aside v-show="liveOpen" class="ws-live" :class="{ 'is-full': liveFull }" aria-label="现场">
        <div class="ws-livehead">
          <div class="ws-livetitle">
            <b>{{ scope === 'me' ? '我的任务' : '现场 · ' + (store.current ? store.current.name : '全局') }}</b>
            <span>{{ liveSummary }}</span>
          </div>
          <div class="ws-liveacts">
            <span class="ws-sync">跟随对话</span>
            <button class="ws-chip" type="button" @click="liveFull = !liveFull">
              {{ liveFull ? '退出全屏' : '全屏' }}
            </button>
          </div>
        </div>

        <div v-if="scope === 'team' && store.currentId" class="ws-filters" role="group" aria-label="任务筛选">
          <button
            v-for="f in filters"
            :key="f.key"
            class="ws-chip"
            :class="{ on: filter === f.key }"
            type="button"
            @click="filter = f.key"
          >{{ f.label }}</button>
        </div>

        <!-- 我的任务：跨项目 -->
        <template v-if="scope === 'me'">
          <div v-for="group in myGroups" :key="group.project" class="ws-mygroup">
            <div class="ws-myproj">{{ group.project }}</div>
            <div v-for="t in group.tasks" :key="t.id" class="ws-myitem">
              <b>{{ t.title }}</b>
              <span>{{ statusOf(t).label }}</span>
            </div>
          </div>
          <div v-if="!myGroups.length" class="ws-empty-small">当前没有派给 {{ meName }} 的任务。</div>
        </template>

        <!-- 全队：预览（默认）或看板（全屏） -->
        <template v-else>
          <!-- 全局：各项目任务分布（队长视野），点一行进入那个项目 -->
          <div v-if="!store.currentId">
            <div class="ws-empty-small">还没绑定项目。下面是全队的任务分布，点一行进入那个项目。</div>
            <button
              v-for="p in overview"
              :key="p.id"
              class="ws-row"
              type="button"
              @click="store.setCurrent(p.id)"
            >
              <span class="ws-rowmain">
                <span class="ws-rowtitle">{{ p.name }}</span>
                <span class="ws-rowmeta">{{ p.total }} 条任务 · 进行中 {{ p.doing }}<template v-if="p.blocked"> · 待解锁 {{ p.blocked }}</template></span>
              </span>
              <span class="ws-arrow">›</span>
            </button>
            <div v-if="!overview.length" class="ws-empty-small">还没有项目。</div>
          </div>
          <div v-else-if="!visibleTasks.length" class="ws-empty-small">
            这个项目还没有任务，跟左边说一句就会长出来。
          </div>
          <div v-else-if="!liveFull" class="ws-preview-list">
            <button
              v-for="t in visibleTasks.slice(0, 4)"
              :key="t.id"
              class="ws-row"
              type="button"
              @click="liveFull = true"
            >
              <i class="ws-dot" :class="dotClass(t)" aria-hidden="true" />
              <span class="ws-rowmain">
                <span class="ws-rowtitle">{{ t.title }}</span>
                <span v-if="isBlocked(t)" class="ws-rowwarn">待解锁</span>
              </span>
              <span class="ws-pava" :class="{ empty: !t.assignee_name }">{{ t.assignee_name ? t.assignee_name.slice(-1) : '+' }}</span>
            </button>
            <div v-if="visibleTasks.length > 4" class="ws-more">
              还有 {{ visibleTasks.length - 4 }} 条，点开看全部
            </div>
            <div class="ws-hint">点上面任意一条 → 展开成全屏看板</div>
          </div>
          <div v-else class="ws-board" :class="{ one: filter !== 'all' }">
            <section v-for="col in visibleColumns" :key="col.key" class="ws-col">
              <div class="ws-colhead">
                <i class="ws-dot" :class="col.dot" aria-hidden="true" />
                <span>{{ col.label }}</span>
                <b>{{ col.tasks.length }}</b>
              </div>
              <article
                v-for="t in col.tasks"
                :key="t.id"
                class="ws-card"
                :class="{ locked: isBlocked(t) }"
              >
                <span class="ws-pri" :class="t.priority">{{ priText(t.priority) }}</span>
                <h4>{{ t.title }}</h4>
                <div v-if="isBlocked(t)" class="ws-cardnote">被前置任务卡住，前置完成后可开工</div>
                <div class="ws-cardfoot">
                  <span class="ws-pava" :class="{ empty: !t.assignee_name }">{{ t.assignee_name ? t.assignee_name.slice(-1) : '+' }}</span>
                  <span class="ws-who">{{ t.assignee_name || '未分配' }}</span>
                </div>
              </article>
            </section>
          </div>
        </template>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { chatApi, knowledgeApi, taskApi, USER_ID } from '../api'
import { useProjectStore } from '../stores/project'
import ChatMessage from '../components/ChatMessage.vue'

const store = useProjectStore()

// 账号体系落地前：先用演示用户的名字当「我」（见 DECISIONS D-003）
const meName = ref('alice')
const scope = ref('team')          // team | me
const filter = ref('all')          // all | todo | doing
const assetsOpen = ref(true)
const liveOpen = ref(true)
const liveFull = ref(false)

const messages = ref([])
const draft = ref('')
const sending = ref(false)
const tasks = ref([])
const mineTasks = ref([])           // 我的任务（跨项目）
const documents = ref([])
const picked = ref(null)
const overview = ref([])            // 全局范围：各项目任务概览（队长视野）
const threadEl = ref(null)

const repoDocs = [
  { name: 'PLAN.md', note: '要什么', text: '仓库根目录 · 唯一事实源：做什么、不做什么、验收标准。Agent 每次对话自动读它。' },
  { name: 'DECISIONS.md', note: '为什么', text: '仓库根目录 · 已经定过的决策与踩过的坑，只追加不改。指派不改变状态就是 D-005。' },
  { name: 'docs/WORKFLOW.md', note: '怎么干', text: 'docs/ 下 · 每轮节奏：产出 → 人拍板 → 落盘。一轮只推进一个能验证的小步。' },
]

const filters = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '未开始' },
  { key: 'doing', label: '进行中' },
]

const STATUS = {
  todo: { label: '待办', dot: 'todo', col: '待办' },
  doing: { label: '进行中', dot: 'doing', col: '进行中' },
  done: { label: '已完成', dot: 'done', col: '已完成' },
}

function statusOf(t) {
  return STATUS[t.status] || { label: t.status, dot: 'todo', col: t.status }
}
function isBlocked(t) {
  return t.status !== 'done' && (t.blocked_by_count || 0) > 0
}
function dotClass(t) {
  if (isBlocked(t)) return 'lock'
  return statusOf(t).dot
}
function priText(p) {
  return { high: '高', medium: '中', low: '低' }[p] || p || '中'
}

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

const visibleTasks = computed(() =>
  filter.value === 'all' ? tasks.value : tasks.value.filter((t) => t.status === filter.value))

const visibleColumns = computed(() =>
  ['todo', 'doing', 'done']
    .filter((k) => filter.value === 'all' || filter.value === k)
    .map((k) => ({
      key: k,
      label: STATUS[k].col,
      dot: STATUS[k].dot,
      tasks: tasks.value.filter((t) => t.status === k),
    })))

const myGroups = computed(() => {
  const map = new Map()
  for (const t of mineTasks.value) {
    const key = t._projectName || '未归属'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(t)
  }
  return [...map.entries()].map(([project, list]) => ({ project, tasks: list }))
})

const liveSummary = computed(() => {
  if (!store.currentId) {
    const total = overview.value.reduce((n, p) => n + p.total, 0)
    return overview.value.length ? `全队 ${overview.value.length} 个项目 · ${total} 条任务` : '还没有项目'
  }
  if (scope.value === 'me') return `${mineTasks.value.length} 条 · 跨全部项目`
  if (!tasks.value.length) return store.currentId ? '还没有任务' : '未绑定项目'
  const done = tasks.value.filter((t) => t.status === 'done').length
  const doing = tasks.value.filter((t) => t.status === 'doing').length
  const locked = tasks.value.filter(isBlocked).length
  return `${done}/${tasks.value.length} 已完成 · ${doing} 进行中${locked ? ` · ${locked} 待解锁` : ''}`
})

// ---------- 取数 ----------
async function loadThread() {
  try {
    const rows = await chatApi.history(store.currentId || null)
    messages.value = rows.map((r) => ({ role: r.role, content: r.content, trace: r.trace || [] }))
  } catch { messages.value = [] }
  scrollThread()
}

async function loadTasks() {
  if (!store.currentId) { tasks.value = []; return }
  try {
    tasks.value = await taskApi.list(store.currentId)
  } catch (e) {
    tasks.value = []
    ElMessage.error('任务加载失败：' + e.message)
  }
}

async function loadDocuments() {
  if (!store.currentId) { documents.value = []; return }
  try {
    documents.value = await knowledgeApi.list(store.currentId)
  } catch { documents.value = [] }
}

async function loadMine() {
  if (!store.projects.length) { mineTasks.value = []; return }
  try {
    const lists = await Promise.all(store.projects.map((p) => taskApi.list(p.id).catch(() => [])))
    const mine = []
    lists.forEach((list, i) => {
      const projectName = store.projects[i].name
      list
        .filter((t) => (t.assignee_name || '') === meName.value)
        .forEach((t) => mine.push({ ...t, _projectName: projectName }))
    })
    mineTasks.value = mine
  } catch { mineTasks.value = [] }
}

// 全局范围：不选项目时，右侧给全队的任务分布，点一行进入那个项目
async function loadOverview() {
  if (!store.projects.length) { overview.value = []; return }
  try {
    const lists = await Promise.all(store.projects.map((p) => taskApi.list(p.id).catch(() => [])))
    overview.value = store.projects.map((p, i) => {
      const list = lists[i]
      return {
        id: p.id,
        name: p.name,
        total: list.length,
        doing: list.filter((t) => t.status === 'doing').length,
        blocked: list.filter((t) => t.status !== 'done' && (t.blocked_by_count || 0) > 0).length,
      }
    })
  } catch { overview.value = [] }
}

async function reloadAll() {
  picked.value = null
  await Promise.all([loadThread(), loadTasks(), loadDocuments()])
  if (scope.value === 'me') await loadMine()
  if (!store.currentId) await loadOverview()
}

async function setScope(next) {
  scope.value = next
  if (next === 'me') await loadMine()
}

function toggleLive() {
  liveOpen.value = !liveOpen.value
  if (!liveOpen.value) liveFull.value = false
}

function pickRepoDoc(doc) {
  picked.value = { kind: 'repo', name: doc.name, text: doc.text }
}

function pickDocument(doc) {
  picked.value = {
    kind: 'doc',
    id: doc.id,
    name: doc.title,
    text: doc.summary || doc.content_preview || `${doc.doc_type || '文档'} · 已进项目记忆，Agent 检索时会读到它。`,
  }
}

// ---------- 对话 ----------
function scrollThread() {
  nextTick(() => {
    if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight
  })
}

async function send(text) {
  const content = (text ?? draft.value).trim()
  if (!content || sending.value) return
  draft.value = ''
  messages.value.push({ role: 'user', content })
  sending.value = true
  scrollThread()
  try {
    const res = await chatApi.send(content, store.currentId || null)
    messages.value.push({ role: 'assistant', content: res.reply, trace: res.trace || [] })
    await Promise.all([loadTasks(), loadDocuments(), store.load()])
    if (scope.value === 'me') await loadMine()
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `出错了：${e.message}（换个说法再试试）` })
  } finally {
    sending.value = false
    scrollThread()
  }
}

// 对话里的实体引用：切上下文、留在这个页面
async function onGoToRef(ref) {
  const pid = ref.kind === 'project' ? ref.id : ref.project_id
  if (!pid) return ElMessage.warning('无法定位该项目，请手动切换')
  store.setCurrent(pid)
  await reloadAll()
}

onMounted(async () => {
  if (!store.projects.length) await store.load()
  await reloadAll()
})

watch(() => store.currentId, () => { reloadAll() })
</script>

<style scoped>
/* 新工作台：一个界面、两个投影。设计规则见仓库 DECISIONS.md（D-001 / D-006） */
.ws {
  --ws-bg: #ffffff;
  --ws-surface: #ffffff;
  --ws-surface2: #fafafa;
  --ws-line: #e3e6e8;
  --ws-line2: #eef0f1;
  --ws-fg: #0c0e11;
  --ws-fg2: #3f454c;
  --ws-fg3: #6b7178;
  --ws-accent: #0f766e;
  --ws-accent-wash: #eff7f6;
  --ws-accent-line: #bfe0dc;
  --ws-warn: #a15c00;
  --ws-warn-wash: #fdf6ec;
  --ws-radius: 8px;
  --ws-radius-sm: 6px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--ws-bg);
  color: var(--ws-fg);
  font-size: 13px;
  line-height: 1.5;
}

/* ---------- 顶栏 ---------- */
.ws-top {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 9px 16px;
  border-bottom: 1px solid var(--ws-line);
  background: var(--ws-surface);
}
.ws-brand { display: flex; align-items: center; gap: 9px; }
.ws-logo {
  width: 26px; height: 26px;
  border-radius: var(--ws-radius-sm);
  background: var(--ws-accent);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.ws-brandtext { display: flex; flex-direction: column; line-height: 1.15; }
.ws-brandtext b { font-weight: 600; font-size: 14px; }
.ws-brandtext i { font-style: normal; font-size: 10px; letter-spacing: 1.4px; color: var(--ws-fg3); }
.ws-scopes, .ws-panels { display: flex; gap: 4px; }
.ws-chip {
  font: inherit;
  font-size: 12px;
  color: var(--ws-fg2);
  background: var(--ws-surface);
  border: 1px solid var(--ws-line);
  border-radius: 999px;
  padding: 3px 11px;
  cursor: pointer;
}
.ws-chip:hover { border-color: var(--ws-fg3); }
.ws-chip.on { color: var(--ws-accent); border-color: var(--ws-accent-line); background: var(--ws-accent-wash); font-weight: 600; }
.ws-crumbs { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.ws-crumb { font-size: 12px; color: var(--ws-fg3); }
.ws-sep { margin-left: 7px; color: var(--ws-line); }
.ws-crumbon {
  font-size: 12.5px; font-weight: 600; color: var(--ws-fg);
  padding: 3px 8px; border: 1px solid var(--ws-line);
  border-radius: var(--ws-radius-sm); background: var(--ws-surface2);
}
.ws-pick { width: 150px; }
.ws-avatar {
  margin-left: auto;
  width: 24px; height: 24px; border-radius: 50%;
  background: var(--ws-accent); color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px;
}

/* ---------- 主体 ---------- */
.ws-main { flex: 1; min-height: 0; display: flex; align-items: stretch; }

/* 左：资产库 */
.ws-assets {
  flex: 0 0 280px;
  min-width: 0;
  padding: 14px;
  border-right: 1px solid var(--ws-line);
  background: var(--ws-surface2);
  overflow-y: auto;
}
.ws-ashead { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.ws-ashead b { font-weight: 600; }
.ws-ashead span { font-size: 11.5px; color: var(--ws-fg3); }
.ws-group { font-size: 11px; letter-spacing: 0.08em; color: var(--ws-fg3); margin: 12px 0 4px; }
.ws-file {
  display: flex; align-items: center; gap: 7px;
  width: 100%; font: inherit; text-align: left;
  padding: 7px 8px; border: 1px solid transparent;
  border-radius: var(--ws-radius-sm); background: transparent;
  color: var(--ws-fg); cursor: pointer;
}
.ws-file:hover { background: var(--ws-surface); }
.ws-file.on { background: var(--ws-surface); border-color: var(--ws-line); }
.ws-mark { width: 8px; height: 8px; border-radius: 2px; background: var(--ws-accent-wash); border: 1px solid var(--ws-accent-line); flex-shrink: 0; }
.ws-filename { flex: 1; min-width: 0; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ws-filenote { font-size: 11px; color: var(--ws-fg3); white-space: nowrap; }
.ws-preview { margin-top: 14px; padding: 10px 11px; border: 1px solid var(--ws-line); border-radius: var(--ws-radius); background: var(--ws-surface); }
.ws-preview-head { font-size: 11.5px; color: var(--ws-fg3); margin-bottom: 5px; }
.ws-preview p { margin: 0; font-size: 12px; color: var(--ws-fg2); line-height: 1.55; }

/* 中：对话 */
.ws-chat { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
.ws-thin { display: flex; flex-direction: column; flex: 1; width: 100%; max-width: 620px; min-width: 0; margin: 0 auto; }
.ws-thread { flex: 1; min-height: 220px; overflow-y: auto; padding: 16px; }
.ws-hello-title { margin: 0 0 10px; color: var(--ws-fg2); }
.ws-suggest { display: flex; flex-wrap: wrap; gap: 6px; }
.ws-act {
  font: inherit; font-size: 12px; cursor: pointer;
  padding: 4px 10px; border: 1px solid var(--ws-line);
  border-radius: var(--ws-radius-sm); background: var(--ws-surface); color: var(--ws-fg2);
}
.ws-typing { color: var(--ws-fg3); font-size: 12.5px; }
.ws-composer { border-top: 1px solid var(--ws-line); padding: 12px 16px 14px; }
.ws-input {
  display: block; width: 100%; box-sizing: border-box;
  font: inherit; font-size: 13px; color: var(--ws-fg);
  padding: 9px 11px; border: 1px solid var(--ws-line);
  border-radius: var(--ws-radius-sm); background: var(--ws-surface);
  resize: none;
}
.ws-input::placeholder { color: var(--ws-fg3); }
.ws-sendrow { display: flex; align-items: center; gap: 10px; margin-top: 9px; }
.ws-note { font-size: 11.5px; color: var(--ws-fg3); }
.ws-send {
  margin-left: auto; font: inherit; font-size: 12.5px; font-weight: 600;
  color: #fff; background: var(--ws-accent); border: 1px solid var(--ws-accent);
  border-radius: var(--ws-radius-sm); padding: 6px 18px; cursor: pointer;
}
.ws-send[disabled] { opacity: 0.5; cursor: default; }

/* 右：现场 */
.ws-live {
  flex: 0 0 300px;
  min-width: 0;
  padding: 14px;
  border-left: 1px solid var(--ws-line);
  background: var(--ws-surface2);
  overflow-y: auto;
  transition: flex-basis 0.22s ease;
}
.ws-main.is-full .ws-assets,
.ws-main.is-full .ws-chat { display: none; }
.ws-main.is-full .ws-live { flex: 0 0 100%; max-width: 100%; background: var(--ws-surface); }
.ws-livehead { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.ws-livetitle { display: flex; flex-direction: column; min-width: 0; }
.ws-livetitle b { font-weight: 600; }
.ws-livetitle span { font-size: 12px; color: var(--ws-fg3); }
.ws-liveacts { display: flex; align-items: center; gap: 6px; }
.ws-sync {
  font-size: 11px; color: var(--ws-accent);
  border: 1px solid var(--ws-accent-line); background: var(--ws-accent-wash);
  border-radius: 999px; padding: 2px 9px; white-space: nowrap;
}
.ws-filters { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 10px; }
.ws-filters .ws-chip { font-size: 11.5px; padding: 2px 9px; }
.ws-preview-list { display: flex; flex-direction: column; }
.ws-row {
  display: flex; align-items: center; gap: 8px;
  width: 100%; font: inherit; text-align: left;
  padding: 8px 2px; border: 0; border-top: 1px solid var(--ws-line2);
  background: transparent; color: var(--ws-fg); cursor: pointer;
}
.ws-row:first-child { border-top: 0; }
.ws-row:hover { background: var(--ws-surface); }
.ws-rowmain { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.ws-rowtitle { font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ws-rowwarn { font-size: 11px; color: var(--ws-warn); }
.ws-rowmeta { font-size: 11px; color: var(--ws-fg3); }
.ws-arrow { color: var(--ws-fg3); }
.ws-dot { width: 8px; height: 8px; border-radius: 50%; background: #9aa0a8; flex-shrink: 0; }
.ws-dot.doing { background: var(--ws-accent); }
.ws-dot.done { background: #0f7a3d; }
.ws-dot.lock { background: var(--ws-warn); }
.ws-pava {
  width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; color: var(--ws-accent);
  background: var(--ws-accent-wash); border: 1px solid var(--ws-accent-line);
}
.ws-pava.empty { background: transparent; border: 1px dashed var(--ws-line); color: var(--ws-fg3); }
.ws-more, .ws-hint, .ws-empty-small { font-size: 11.5px; color: var(--ws-fg3); padding-top: 8px; }

/* 全屏看板 */
.ws-board { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.ws-board.one { grid-template-columns: 1fr; }
.ws-col {
  display: flex; flex-direction: column; gap: 8px;
  padding: 10px; border: 1px solid var(--ws-line);
  border-radius: var(--ws-radius); background: var(--ws-surface);
  min-height: 200px;
}
.ws-colhead { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ws-fg2); }
.ws-colhead b { margin-left: auto; font-weight: 600; color: var(--ws-fg3); }
.ws-card { padding: 9px 10px; border: 1px solid var(--ws-line2); border-radius: var(--ws-radius-sm); background: var(--ws-surface); }
.ws-card.locked { background: var(--ws-warn-wash); border-color: #f0dcbb; }
.ws-card h4 { margin: 6px 0 7px; font-size: 12.5px; font-weight: 500; }
.ws-cardnote { font-size: 11.5px; color: var(--ws-warn); margin-bottom: 7px; }
.ws-cardfoot { display: flex; align-items: center; gap: 6px; }
.ws-who { font-size: 11.5px; color: var(--ws-fg3); }
.ws-pri {
  display: inline-block; font-size: 11px; padding: 1px 7px;
  border-radius: 999px; border: 1px solid var(--ws-line);
  color: var(--ws-fg2); background: var(--ws-surface2);
}
.ws-pri.high { color: #b42318; border-color: #f0c2bc; background: #fdf3f2; }
.ws-pri.medium { color: #8a5a12; border-color: #e6d3ac; background: #fff8ef; }

/* 我的任务 */
.ws-mygroup { margin-bottom: 12px; }
.ws-myproj { font-size: 11.5px; color: var(--ws-fg3); margin-bottom: 5px; }
.ws-myitem {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 10px; margin-bottom: 6px;
  border: 1px solid var(--ws-line); border-radius: var(--ws-radius);
  background: var(--ws-surface);
}
.ws-myitem b { font-weight: 500; font-size: 12.5px; }
.ws-myitem span { font-size: 11.5px; color: var(--ws-fg3); white-space: nowrap; }

@media (prefers-reduced-motion: reduce) {
  .ws-live { transition: none; }
}
@media (max-width: 900px) {
  .ws-assets { display: none; }
  .ws-live { flex: 0 0 46%; }
  .ws-board { grid-template-columns: 1fr; }
}
</style>
