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

      <!-- 窄屏（≤900px）左栏会整块收起，名册改从顶栏进 -->
      <div class="ws-memberbtn">
        <button
          class="ws-chip ws-memberchip"
          :class="{ on: rosterOpen }"
          type="button"
          :aria-expanded="rosterOpen"
          @click="rosterOpen = !rosterOpen"
        >成员 · {{ members.length }}</button>
        <div v-if="rosterOpen" class="ws-pop ws-poptop" role="dialog" aria-label="小队成员">
          <div class="ws-pophead"><b>小队成员</b><span>占位成员带邀请码</span></div>
          <div v-for="m in members" :key="m.id" class="ws-poprow static">
            <span class="ws-pava" :class="{ empty: m.status !== 'active' }">{{ m.name.slice(-1) }}</span>
            <span class="ws-popname">{{ m.name }}</span>
            <span v-if="m.status !== 'active'" class="ws-code">{{ m.invite_code }}</span>
            <span class="ws-tag" :class="m.status === 'active' ? 'ok' : 'wait'">
              {{ m.status === 'active' ? '已注册' : '待认领' }}
            </span>
          </div>
          <div class="ws-popnew">
            <input
              v-model="newMemberName"
              class="ws-minput"
              type="text"
              placeholder="手填名字…"
              aria-label="手填成员名字"
              @keydown.enter="addRosterMember"
            />
            <button class="ws-btn solid" type="button" @click="addRosterMember">出邀请码</button>
          </div>
        </div>
      </div>

      <button
        class="ws-chip ws-fontbtn"
        type="button"
        :aria-label="'字号：' + fontLabel + '，点击切换下一档'"
        @click="cycleFont"
      >Aa · {{ fontLabel }}</button>
      <span class="ws-sr" aria-live="polite">字号已切到{{ fontLabel }}</span>

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

        <!-- 小队成员名册：占位成员（还没注册的人）也能被指派，邀请码发给对方认领 -->
        <div class="ws-group">小队成员 · 名册</div>
        <MemberRoster
          :members="members"
          v-model:name="newMemberName"
          @add="addRosterMember"
        />

        <div class="ws-preview">
          <div class="ws-preview-head">{{ picked ? picked.name : '点左侧任意一项' }}</div>
          <p>{{ picked ? picked.text : '这里显示你选中的资料的摘要。' }}</p>
          <template v-if="picked && picked.body">
            <div class="ws-preview-body">{{ picked.body }}</div>
            <p class="ws-preview-foot">{{ picked.foot }}</p>
          </template>
        </div>
      </aside>

      <!-- ===== 中：对话（居中） ===== -->
      <ChatPanel
        ref="chatRef"
        v-model:draft="draft"
        :messages="messages"
        :sending="sending"
        @send="send"
        @goto="onGoToRef"
      />

      <!-- ===== 右：现场（预览 → 全屏） ===== -->
      <LivePanel
        v-show="liveOpen"
        :scope="scope"
        :live-full="liveFull"
        :filter="filter"
        :project-name="store.current ? store.current.name : ''"
        :has-project="!!store.currentId"
        :summary="liveSummary"
        :me-name="meName"
        :overview="overview"
        :visible-tasks="visibleTasks"
        :visible-columns="visibleColumns"
        :my-groups="myGroups"
        :members="members"
        :assign-for="assignFor"
        :assign-name="assignNewName"
        @update:live-full="liveFull = $event"
        @update:filter="filter = $event"
        @update:assign-name="assignNewName = $event"
        @open-project="store.setCurrent($event)"
        @toggle-assign="toggleAssign"
        @assign="onAssign"
        @create-assign="onCreateAssign"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { chatApi, knowledgeApi, memberApi, taskApi, USER_ID } from '../api'
import { useProjectStore } from '../stores/project'
// 工作台按组件拆开（D-026）：常量与纯函数在 workspace/constants.js，四个组件各管一块
import ChatPanel from '../components/workspace/ChatPanel.vue'
import LivePanel from '../components/workspace/LivePanel.vue'
import MemberRoster from '../components/workspace/MemberRoster.vue'
import { DOC_PREVIEW_CHARS, FONT_SCALES, STATUS, isBlocked, repoDocs }
  from '../components/workspace/constants.js'

const store = useProjectStore()

// 名册（小队成员）：占位成员也能被指派，注册后认领（D-017 / D-018）
const members = ref([])
const myMember = computed(() => members.value.find((m) => m.user_id === USER_ID) || null)
// 「我」= 当前账号在名册里对应的成员；名册还没到位时回退到演示用户名（D-003 的过渡）
const meName = computed(() => myMember.value?.name || 'alice')
const scope = ref('team')          // team | me
const filter = ref('all')          // all | todo | doing
const assetsOpen = ref(true)
const liveOpen = ref(true)
const liveFull = ref(false)

// 字号三档：改的是 html 的 font-size，全站 rem 字号跟着缩放，档位记在本地
const fontIndex = ref(1)
const fontLabel = computed(() => FONT_SCALES[fontIndex.value].label)

function applyFontScale(index, persist = true) {
  fontIndex.value = index
  document.documentElement.style.fontSize = FONT_SCALES[index].root
  if (persist) {
    try { localStorage.setItem('squad.fontScale', FONT_SCALES[index].key) } catch { /* 隐私模式下忽略 */ }
  }
}

function cycleFont() {
  applyFontScale((fontIndex.value + 1) % FONT_SCALES.length)
}

const messages = ref([])
const draft = ref('')
const sending = ref(false)
const tasks = ref([])
const mineTasks = ref([])           // 我的任务（跨项目）
const documents = ref([])
const picked = ref(null)
const overview = ref([])            // 全局范围：各项目任务概览（队长视野）
const chatRef = ref(null)   // 对话组件：滚动由它自己管，父组件只在需要时喊一声

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
        .filter(isMine)
        .forEach((t) => mine.push({ ...t, _projectName: projectName }))
    })
    mineTasks.value = mine
  } catch { mineTasks.value = [] }
}

// 我的任务：按成员身份（assignee_id）过滤；名册还没到位时回退到名字匹配（D-010 的过渡办法）
function isMine(t) {
  const me = myMember.value
  if (me) return t.assignee_id === me.id
  return (t.assignee_name || '') === meName.value
}

async function loadMembers() {
  try { members.value = await memberApi.list() } catch { members.value = [] }
}

// ---------- 指派（D-017 / D-018）：只改负责人、不改状态；就地选人，不弹模态 ----------
const assignFor = ref(0)         // 哪张卡片的指派浮层开着（存任务 id，0 = 都关着）
const assignNewName = ref('')    // 浮层里「新建成员」输入
const rosterOpen = ref(false)    // 顶栏名册浮层（窄屏用）
const newMemberName = ref('')    // 左栏名册「手填名字」输入
const assignBusy = ref(false)

function toggleAssign(t) {
  assignFor.value = assignFor.value === t.id ? 0 : t.id
  assignNewName.value = ''
}

// 看板卡把事件抛上来（D-026 拆组件后）：这里把"哪张卡"补回去再走原逻辑
async function onAssign({ task, member }) {
  await assignTo(task, member)
}

async function onCreateAssign({ task }) {
  await addMemberAndAssign(task)
}

async function assignTo(t, m) {
  if (assignBusy.value) return
  assignBusy.value = true
  try {
    const updated = await taskApi.update(t.id, { assignee_id: m.id })
    const i = tasks.value.findIndex((x) => x.id === t.id)
    if (i >= 0) tasks.value[i] = updated
    assignFor.value = 0
    ElMessage.success(`已把「${t.title}」派给 ${m.name}`)
    if (scope.value === 'me') await loadMine()
  } catch (e) {
    ElMessage.error('指派失败：' + e.message)
  } finally {
    assignBusy.value = false
  }
}

async function addMember(rawName) {
  const name = (rawName || '').trim()
  if (!name) return null
  try {
    const m = await memberApi.create(name)
    members.value = [...members.value, m]
    return m
  } catch (e) {
    // 同名不自动合并：让用户自己确认是不是同一个人（PLAN §5）
    if (String(e.message).includes('同名')) ElMessage.warning(e.message)
    else ElMessage.error('加成员失败：' + e.message)
    return null
  }
}

async function addRosterMember() {
  const m = await addMember(newMemberName.value)
  if (!m) return
  newMemberName.value = ''
  ElMessage.success(`「${m.name}」已进名册：待认领 · 邀请码 ${m.invite_code}`)
}

async function addMemberAndAssign(t) {
  const m = await addMember(assignNewName.value)
  if (!m) return
  assignNewName.value = ''
  await assignTo(t, m)
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
  await Promise.all([loadThread(), loadTasks(), loadDocuments(), loadMembers()])
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
  // 项目记忆文档：点开要能看到正文（原来是只有一行说明，演示时看不出"资产库里真有东西"）。
  // 侧栏窄，所以只渲染前 DOC_PREVIEW_CHARS 字（超出部分在框内滚动 + 底部注明全文体量）。
  const full = (doc.content || '').trim()
  const shown = full.length > DOC_PREVIEW_CHARS ? `${full.slice(0, DOC_PREVIEW_CHARS)}…` : full
  picked.value = {
    kind: 'doc',
    id: doc.id,
    name: doc.title,
    text: doc.summary || doc.content_preview || `${doc.doc_type || '文档'} · 已进项目记忆，Agent 检索时会读到它。`,
    body: shown,
    foot: full.length > shown.length
      ? `预览前 ${DOC_PREVIEW_CHARS} 字 · 全文 ${full.length.toLocaleString()} 字，Agent 检索时读的是全文`
      : `全文 ${full.length.toLocaleString()} 字 · Agent 检索时会读到它`,
  }
}

// ---------- 对话 ----------
function scrollThread() {
  chatRef.value?.scrollToBottom()   // 滚动归 ChatPanel 管（D-014：只有对话区滚）
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
  let saved = null
  try { saved = localStorage.getItem('squad.fontScale') } catch { /* 隐私模式下忽略 */ }
  const savedIndex = FONT_SCALES.findIndex((f) => f.key === saved)
  applyFontScale(savedIndex >= 0 ? savedIndex : 1, false)
  if (!store.projects.length) await store.load()
  await reloadAll()
})

watch(() => store.currentId, () => { reloadAll() })
</script>


<!-- 样式已整块搬到 src/assets/workspace.css（D-026）：拆组件后父组件的 scoped
     样式碰不到子组件内部，而这些类名都以 .ws- 前缀命名空间化，放全局是安全的。 -->
