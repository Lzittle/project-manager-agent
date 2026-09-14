<template>
  <div class="wb">
    <!-- 上下文条：现在在哪儿对话 / 在哪个项目做事 -->
    <div class="ctx-strip">
      <span class="ctx-dot" :class="isBound ? 'bound' : 'global'" />
      <span v-if="isBound" class="ctx-text">
        正在 <b class="ctx-proj">{{ store.current.name }}</b> 里对话
        <span class="ctx-sub">— Agent 会聚焦本项目，动作都落在这里</span>
      </span>
      <span v-else class="ctx-text">
        全局对话
        <span class="ctx-sub">— 可以让 Agent 创建 / 管理任意项目</span>
      </span>

      <div class="ctx-actions">
        <button class="ctx-link" @click="go('/overview')">总览</button>
        <button class="ctx-link" @click="go('/knowledge')">项目记忆</button>
        <button class="ctx-link primary" @click="go('/board')">打开看板 ›</button>
      </div>
    </div>

    <!-- 滚动主体：空态引导 or 对话记录 -->
    <div class="wb-body">
      <!-- ========== 空态：问候 + 示例 + 今日工作区 ========== -->
      <template v-if="!messages.length && !loadingHistory">
        <div class="hero">
          <div class="hero-eyebrow">SQUAD · 小队智脑</div>
          <h1 class="hero-title">{{ heroTitle }}</h1>
          <p class="hero-sub">{{ heroSub }}</p>
          <div class="hero-tip">
            <el-icon><MagicStick /></el-icon>
            <span>示例：{{ heroExample }}</span>
          </div>
        </div>

        <div class="chips">
          <button
            v-for="q in quickExamples"
            :key="q"
            class="chip"
            @click="send(q)"
          >{{ q }}</button>
        </div>

        <!-- 当前项目小结（已绑定且有数据时） -->
        <div v-if="isBound && ctxStats" class="mini-card">
          <div class="ring-wrap">
            <div class="ring" :style="{ background: ringBg }" />
            <span class="ring-num">{{ ctxStats.pct }}%</span>
          </div>
          <div class="mini-main">
            <div class="mini-title">{{ store.current.name }} · 完成 {{ ctxStats.done }}/{{ ctxStats.total }}</div>
            <div class="mini-meta">
              <span class="mini-count">进行中 {{ ctxStats.doing }}</span>
              <span class="mini-count warn" :class="{ zero: !ctxStats.blocked }">
                {{ ctxStats.blocked ? `待解锁 ${ctxStats.blocked}` : '没有卡点' }}
              </span>
              <button class="mini-go" @click="go('/board')">去整理 ›</button>
            </div>
          </div>
        </div>

        <!-- 从这里开始：三块面板入口 -->
        <div class="sec-label">或者，从这里开始</div>
        <div class="entries">
          <button class="entry" @click="go('/board')">
            <span class="entry-ic ic-tickets"><el-icon><Tickets /></el-icon></span>
            <span class="entry-main">
              <span class="entry-title">项目看板</span>
              <span class="entry-desc">把当前项目的任务拖一拖，状态一目了然</span>
            </span>
            <span class="entry-go"><el-icon><ArrowRight /></el-icon></span>
          </button>
          <button class="entry" @click="go('/overview')">
            <span class="entry-ic ic-chart"><el-icon><DataAnalysis /></el-icon></span>
            <span class="entry-main">
              <span class="entry-title">总览</span>
              <span class="entry-desc">所有项目的进度与「待解锁」，一眼看清</span>
            </span>
            <span class="entry-go"><el-icon><ArrowRight /></el-icon></span>
          </button>
          <button class="entry" @click="go('/knowledge')">
            <span class="entry-ic ic-doc"><el-icon><Document /></el-icon></span>
            <span class="entry-main">
              <span class="entry-title">项目记忆</span>
              <span class="entry-desc">存文档、录纪要，Agent 以后问得到</span>
            </span>
            <span class="entry-go"><el-icon><ArrowRight /></el-icon></span>
          </button>
        </div>

        <div class="demo-row">
          <span class="demo-hint">不清楚 Agent 能做什么？</span>
          <el-button type="primary" plain :loading="demoBusy" @click="runDemo">
            ▶ 一键演示：从零建项目并规划任务
          </el-button>
        </div>
      </template>

      <!-- ========== 对话记录 ========== -->
      <template v-else-if="messages.length">
        <div v-loading="loadingHistory" class="thread" ref="threadRef">
          <ChatMessage
            v-for="(m, i) in messages"
            :key="i"
            :role="m.role"
            :content="m.content"
            :trace="m.trace"
            @goto="gotoRef"
          />
          <div v-if="loading" class="typing">
            <ChatMessage role="assistant" content="正在思考并调用工具…" />
          </div>
        </div>

        <!-- 半自动沉淀提示：结论/决策型回复 + 执行过写工具 → 问是否入库 -->
        <div v-if="isBound && suggestVisible" class="suggest">
          <el-icon class="suggest-ic"><InfoFilled /></el-icon>
          <span class="suggest-text">这段对话像有值得沉淀的结论，整理成会议纪要存进「{{ store.current.name }}」的记忆？</span>
          <el-button size="small" type="primary" :loading="savingNote" @click="saveMeeting">整理入库</el-button>
          <el-button size="small" text @click="suggestVisible = false">先不用</el-button>
        </div>
      </template>
    </div>

    <!-- ========== 输入区（常驻底部） ========== -->
    <div class="composer">
      <div class="composer-box">
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          resize="none"
          placeholder="直接说你的目标 / 想法…"
          @keydown.enter.exact.prevent="send()"
        />
        <div class="composer-foot">
          <div class="composer-left">
            <el-tooltip
              :content="isBound ? '把本次对话的结论整理成纪要，存进项目记忆' : '绑定一个项目后，才能把结论归档成纪要'"
              placement="top"
            >
              <span>
                <el-button
                  :icon="DocumentAdd"
                  :disabled="!isBound || !messages.length"
                  :loading="savingNote"
                  @click="saveMeeting"
                >存为纪要</el-button>
              </span>
            </el-tooltip>
            <el-tooltip content="清空这段对话（换个问题重新开始）" placement="top">
              <el-button :icon="Refresh" circle title="新会话" @click="resetChat" />
            </el-tooltip>
          </div>
          <div class="composer-right">
            <el-button
              type="primary"
              size="large"
              class="send-btn"
              :loading="loading"
              :disabled="!draft.trim() && !loading"
              @click="send()"
            >
              <span v-if="!loading">发送</span>
              <span v-if="!loading" class="send-kbd">Enter</span>
            </el-button>
          </div>
        </div>
      </div>
      <div class="composer-note">Enter 发送 · Shift+Enter 换行 · Squad 会自己调用工具完成任务</div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  MagicStick, Tickets, DataAnalysis, Document, ArrowRight,
  Refresh, DocumentAdd, InfoFilled,
} from '@element-plus/icons-vue'
import { chatApi, taskApi } from '../api'
import { useProjectStore } from '../stores/project'
import ChatMessage from '../components/ChatMessage.vue'

const store = useProjectStore()
const router = useRouter()

const messages = ref([])
const draft = ref('')
const loading = ref(false)
const loadingHistory = ref(false)
const demoBusy = ref(false)
const savingNote = ref(false)
const suggestVisible = ref(false)
const ctxStats = ref(null)
const threadRef = ref(null)

const isBound = computed(() => store.currentId > 0 && !!store.current)
const contextId = computed(() => (store.currentId > 0 ? store.currentId : null))

const boundName = computed(() => store.current?.name || '')
const projectCount = computed(() => store.projects.length)

// 问候随上下文变化：有项目可绑就点明「在这个项目里干活」
const heroTitle = computed(() =>
  isBound.value ? `「${boundName.value}」今天想推进什么？` : '嗨，今天想推进什么？')
const heroSub = computed(() =>
  isBound.value
    ? '说一句目标，Squad 会在这个项目里规划、拆任务、查进度，每一步都能回放。'
    : '说一句目标，Squad 自己规划任务、建看板、查进度——不用填一堆表格。')
const heroExample = computed(() =>
  isBound.value
    ? `给「${boundName.value}」规划 / 项目进度怎么样了 / 帮我加个任务`
    : '帮我创建项目「短视频运营」并规划任务 / 我有哪些项目')

// 空态示例：优先以「当前/首个项目」真实名称生成，保证点下去一定有效
const quickExamples = computed(() => {
  const ps = store.projects
  const bound = isBound.value ? boundName.value : ps[0]?.name
  if (bound) {
    return [
      `帮「${bound}」规划几个任务`,
      `给「${bound}」加一个任务：整理待办清单`,
      '查看我有哪些项目',
    ]
  }
  return ['帮我创建项目「官网改版」并自动规划任务', '查看我有哪些项目']
})

const ringBg = computed(() => {
  const pct = ctxStats.value?.pct || 0
  const color = ctxStats.value && ctxStats.value.pct === 100
    ? 'var(--el-color-success)' : 'var(--el-color-primary)'
  return `conic-gradient(${color} ${pct * 3.6}deg, var(--el-fill-color) ${pct * 3.6}deg)`
})

// ---------- 对话上下文 / 历史 ----------
async function loadHistory(projectId = null) {
  loadingHistory.value = true
  try {
    const rows = await chatApi.history(projectId)
    messages.value = rows.map((r) => ({
      role: r.role,
      content: r.content,
      trace: r.trace || [],
    }))
  } catch { /* 历史加载失败忽略 */ }
  finally { loadingHistory.value = false }
}

watch(contextId, (id) => {
  if (demoBusy.value) return
  suggestVisible.value = false
  messages.value = []
  ctxStats.value = null
  if (id) fetchCtxStats(id)
  loadHistory(id)
})

// ---------- 当前项目小结 ----------
async function fetchCtxStats(projectId) {
  try {
    const tasks = await taskApi.list(projectId)
    const total = tasks.length
    const done = tasks.filter((t) => t.status === 'done').length
    const doing = tasks.filter((t) => t.status === 'doing').length
    const blocked = tasks.filter((t) => t.status !== 'done' && (t.blocked_by_count || 0) > 0).length
    ctxStats.value = {
      total, done, doing, blocked,
      pct: total ? Math.round((done / total) * 100) : 0,
    }
  } catch { /* 统计失败忽略 */ }
}

// ---------- 沉淀：半自动提示 + 手动存纪要 ----------
const SUGGEST_RE = /结论|决策|决定|确定|采用|约定|待办|风险|下一步|方案/
function maybeSuggest(text, trace) {
  if (!isBound.value || suggestVisible.value || demoBusy.value) return
  const writeSteps = (trace || []).filter(
    (s) => s.ok && !['none', 'search_knowledge', 'list_tasks', 'list_projects'].includes(s.tool),
  )
  if (!writeSteps.length) return          // 纯查询/闲聊不提示
  if (!SUGGEST_RE.test(text || '')) return
  suggestVisible.value = true
}

async function saveMeeting() {
  if (!contextId.value) return ElMessage.warning('绑定一个项目后，才能把结论归档成纪要')
  savingNote.value = true
  try {
    const r = await chatApi.meetingSummary(contextId.value)
    ElMessage.success(`已把对话沉淀成纪要「${r.title}」，可在「项目记忆」查看`)
    suggestVisible.value = false
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    savingNote.value = false
  }
}

// ---------- 发送 ----------
async function send(text) {
  const content = (text ?? draft.value).trim()
  if (!content || loading.value) return
  draft.value = ''
  messages.value.push({ role: 'user', content })
  loading.value = true
  scrollThread()
  try {
    const res = await chatApi.send(content, contextId.value)
    messages.value.push({ role: 'assistant', content: res.reply, trace: res.trace || [] })
    maybeSuggest(res.reply, res.trace || [])
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `出错了：${e.message}（可换个说法再试）` })
  } finally {
    loading.value = false
    scrollThread()
  }
}

// 实体引用跳转：任务/项目 chip → 打开所属项目看板
function gotoRef(ref) {
  const pid = ref.kind === 'project' ? ref.id : ref.project_id
  if (!pid) return ElMessage.warning('无法定位该项目，请手动切换')
  store.setCurrent(pid)
  router.push('/board')
}

// 一键演示：建项目 → 绑定 → 规划任务 → 查任务（展示多工具执行轨迹）
const DEMO_NAME = '官网改版'
async function runDemo() {
  if (demoBusy.value || loading.value) return
  demoBusy.value = true
  try {
    if (!store.projects.length) await store.load()
    let p = store.projects.find((x) => x.name === DEMO_NAME)
    if (!p) {
      const list = (await store.create(DEMO_NAME, 'Agent 一键演示项目（可随时删除）')) || []
      p = list.find((x) => x.name === DEMO_NAME)
    }
    if (!p) { ElMessage.error('演示项目创建失败，请稍后重试'); return }
    store.setCurrent(p.id)
    resetChat()
    if (contextId.value) await fetchCtxStats(contextId.value)
    const exist = await taskApi.list(p.id).catch(() => [])
    if (!exist.length) await send('帮我规划几个任务')
    await send('现在有哪些任务？')
    ElMessage.success('演示完成：已展示 Agent 建项目 + 规划 + 查询的完整执行轨迹')
  } finally {
    demoBusy.value = false
  }
}

function resetChat() {
  messages.value = []
  suggestVisible.value = false
}

function go(path) {
  router.push(path)
}

function scrollThread() {
  nextTick(() => {
    if (threadRef.value) threadRef.value.scrollTop = threadRef.value.scrollHeight
  })
}

onMounted(async () => {
  if (!store.projects.length) await store.load()
  if (contextId.value) fetchCtxStats(contextId.value)
  await loadHistory(contextId.value)
})
</script>

<style scoped>
.wb {
  height: calc(100vh - 128px);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ---------- 上下文条 ---------- */
.ctx-strip {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}
.ctx-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ctx-dot.bound { background: var(--el-color-primary); box-shadow: 0 0 0 3px var(--el-color-primary-light-9); }
.ctx-dot.global { background: var(--el-text-color-placeholder); box-shadow: 0 0 0 3px var(--el-fill-color-dark); }
.ctx-text { font-size: 13px; color: var(--el-text-color-regular); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ctx-proj { color: var(--el-text-color-primary); font-weight: 700; }
.ctx-sub { color: var(--el-text-color-placeholder); margin-left: 6px; }
.ctx-actions { margin-left: auto; display: flex; gap: 4px; flex-shrink: 0; }
.ctx-link {
  border: none; background: none; cursor: pointer;
  font-size: 12px; color: var(--el-text-color-secondary);
  padding: 4px 8px; border-radius: 7px;
  transition: background 0.15s var(--squad-ease), color 0.15s var(--squad-ease);
}
.ctx-link:hover { background: var(--el-fill-color); color: var(--el-text-color-primary); }
.ctx-link.primary { color: var(--el-color-primary-dark-2); background: var(--el-color-primary-light-9); font-weight: 600; }
.ctx-link.primary:hover { background: var(--el-color-primary-light-8); }

/* ---------- 主体滚动区 ---------- */
.wb-body { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 2px 8px; }
.thread { display: flex; flex-direction: column; padding: 4px 2px 8px; }
.typing { opacity: 0.72; }
.suggest {
  display: flex; align-items: center; gap: 10px;
  margin: 8px 2px 0;
  padding: 9px 12px;
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: 10px;
}
.suggest-ic { color: var(--el-color-warning); flex-shrink: 0; }
.suggest-text { flex: 1; color: var(--el-color-warning-dark-2); font-size: 13px; line-height: 1.6; }

/* ---------- 空态：问候 ---------- */
.hero { padding: 22px 4px 6px; }
.hero-eyebrow { font-size: 11px; letter-spacing: 0.2em; color: var(--el-color-primary); font-weight: 700; margin-bottom: 10px; }
.hero-title { font-size: 30px; font-weight: 800; color: var(--el-text-color-primary); letter-spacing: -0.02em; line-height: 1.25; }
.hero-sub { margin-top: 8px; font-size: 14px; color: var(--el-text-color-secondary); line-height: 1.7; }
.hero-tip {
  margin-top: 14px;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 12px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary-dark-2);
  border-radius: 999px;
  font-size: 12px;
}
.hero-tip .el-icon { font-size: 14px; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 4px 4px; }
.chip {
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  font-size: 12px;
  padding: 5px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s var(--squad-ease);
}
.chip:hover { border-color: var(--el-color-primary-light-7); color: var(--el-color-primary-dark-2); background: var(--el-color-primary-light-9); }

/* ---------- 空态：当前项目小结 ---------- */
.mini-card {
  margin: 18px 4px 4px;
  padding: 14px 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  display: flex; align-items: center; gap: 16px;
}
.ring-wrap { position: relative; width: 52px; height: 52px; flex-shrink: 0; }
.ring { width: 52px; height: 52px; border-radius: 50%; }
.ring-num {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 800; color: var(--el-text-color-primary);
}
.mini-main { flex: 1; min-width: 0; }
.mini-title { font-size: 15px; font-weight: 700; color: var(--el-text-color-primary); }
.mini-meta { margin-top: 6px; display: flex; align-items: center; gap: 14px; font-size: 13px; color: var(--el-text-color-secondary); }
.mini-count.warn { color: var(--el-color-warning); font-weight: 600; }
.mini-count.warn.zero { color: var(--el-color-success); font-weight: 600; }
.mini-go {
  margin-left: auto;
  border: none; background: var(--el-color-primary-light-9); color: var(--el-color-primary-dark-2);
  font-size: 12px; font-weight: 600; padding: 5px 11px; border-radius: 8px; cursor: pointer;
}
.mini-go:hover { background: var(--el-color-primary-light-8); }

/* ---------- 空态：入口卡片 ---------- */
.sec-label {
  margin: 22px 4px 8px;
  font-size: 12px; color: var(--el-text-color-placeholder);
  letter-spacing: 0.06em; font-weight: 600;
}
.entries { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0 4px; }
.entry {
  display: flex; align-items: flex-start; gap: 12px;
  text-align: left;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  border-radius: 14px;
  padding: 16px;
  cursor: pointer;
  transition: box-shadow 0.18s var(--squad-ease), border-color 0.18s var(--squad-ease), transform 0.18s var(--squad-ease);
}
.entry:hover { border-color: var(--el-color-primary-light-7); box-shadow: var(--squad-shadow-hover); transform: translateY(-2px); }
.entry-ic {
  width: 38px; height: 38px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 19px; flex-shrink: 0;
}
.ic-tickets { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.ic-chart { background: var(--el-color-success-light-9); color: var(--el-color-success-dark-2); }
.ic-doc { background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2); }
.entry-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.entry-title { font-size: 14px; font-weight: 700; color: var(--el-text-color-primary); }
.entry-desc { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.55; }
.entry-go { color: var(--el-text-color-placeholder); align-self: center; transition: color 0.15s var(--squad-ease); }
.entry:hover .entry-go { color: var(--el-color-primary); }

.demo-row { margin: 22px 4px 8px; display: flex; align-items: center; gap: 10px; }
.demo-hint { font-size: 12px; color: var(--el-text-color-placeholder); }

/* ---------- 输入区 ---------- */
.composer-box {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 14px;
  padding: 10px 12px 8px;
  box-shadow: var(--el-box-shadow-light);
  transition: border-color 0.15s var(--squad-ease), box-shadow 0.15s var(--squad-ease);
}
.composer-box:focus-within { border-color: var(--el-color-primary); box-shadow: 0 0 0 3px var(--el-color-primary-light-9); }
.composer-box :deep(.el-textarea__inner) { box-shadow: none !important; padding: 2px 2px; font-size: 14px; }
.composer-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.composer-left { display: flex; align-items: center; gap: 4px; }
.composer-right { display: flex; align-items: center; }
.send-btn { height: 36px; padding: 0 18px; }
.send-kbd {
  margin-left: 8px;
  font-size: 11px; font-weight: 400;
  padding: 1px 6px; border-radius: 5px;
  background: rgba(255, 255, 255, 0.22);
}
.composer-note { text-align: center; font-size: 11px; color: var(--el-text-color-placeholder); margin-top: 8px; }

@media (max-width: 820px) {
  .entries { grid-template-columns: 1fr; }
  .ctx-sub { display: none; }
  .wb { height: auto; min-height: calc(100vh - 128px); }
}
</style>
