<template>
  <div class="chat-page">
    <!-- 会话控制条 -->
    <div class="chat-bar">
      <el-select v-model="bindProject" placeholder="绑定项目（可选）" clearable style="width: 240px">
        <el-option v-for="p in store.projects" :key="p.id" :value="p.id" :label="p.name" />
      </el-select>
      <span class="hint">
        {{ bindProject ? '已绑定项目：Agent 会优先检索该项目知识库' : '未绑定项目：可让 Agent 创建/管理任意项目' }}
      </span>
      <el-button :icon="Refresh" circle title="清空会话" @click="resetChat" />
    </div>

    <!-- 空态引导（无消息时：能力说明 + 从真实项目动态生成的示例） -->
    <div v-if="!messages.length && !loading" class="guide">
      <div class="guide-title">和你的项目管理 Agent 对话</div>
      <div class="guide-sub">用一句话下指令，Agent 会自动调用工具把事办成，过程全程可见：</div>
      <ul class="guide-bullets">
        <li>新建项目、一句话自动规划任务，结果直接落到看板</li>
        <li>绑定项目后问答，答案来自上传到知识库的文档（需求、方案、验收标准）</li>
        <li>用自然语言推进任务：加任务、标记完成、查进度，看板实时同步</li>
      </ul>
      <div class="guide-actions">
        <el-button type="primary" plain :loading="demoBusy" @click="runDemo">
          ▶ 一键演示：Agent 从零建项目并规划
        </el-button>
      </div>
      <div class="chips">
        <el-tag
          v-for="q in quickExamples"
          :key="q"
          class="chip"
          effect="plain"
          @click="send(q)"
        >{{ q }}</el-tag>
      </div>
      <div v-if="!bindProject && store.projects.length" class="guide-note">
        提示：点右上角绑定项目后，Agent 会聚焦该项目执行，避免任务建错项目
      </div>
    </div>

    <!-- 消息区 -->
    <div ref="scrollRef" class="msg-area">
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

    <!-- 输入区 -->
    <div class="input-bar">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="输入你的需求，Enter 发送，Shift+Enter 换行"
        @keydown.enter.exact.prevent="send()"
      />
      <el-button type="primary" size="large" :icon="Promotion" :loading="loading" @click="send()">
        发送
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Promotion, Refresh } from '@element-plus/icons-vue'
import { chatApi, taskApi } from '../api'
import { useProjectStore } from '../stores/project'
import ChatMessage from '../components/ChatMessage.vue'

const store = useProjectStore()
const router = useRouter()
const messages = ref([])
const draft = ref('')
const loading = ref(false)
const bindProject = ref(null)
const demoBusy = ref(false)
const scrollRef = ref(null)

// 空态示例：优先以「当前绑定/首个项目」真实名称生成，保证点下去一定有效
const quickExamples = computed(() => {
  const ps = store.projects
  const boundName = bindProject.value
    ? ps.find((p) => p.id === bindProject.value)?.name
    : ps[0]?.name
  if (boundName) {
    return [
      `帮「${boundName}」规划几个任务`,
      `给「${boundName}」加一个任务：整理待办清单`,
      '查看我有哪些项目',
    ]
  }
  return ['帮我创建项目「官网改版」并自动规划任务', '查看我有哪些项目']
})

async function loadHistory(projectId = null) {
  try {
    const rows = await chatApi.history(projectId)
    messages.value = rows.map((r) => ({
      role: r.role,
      content: r.content,
      trace: r.trace || [],
    }))
  } catch { /* 历史加载失败忽略 */ }
}

// 切换绑定项目 -> 加载该项目自己的对话上下文（防止跨项目串扰）；演示脚本运行时跳过
watch(bindProject, (val) => {
  if (demoBusy.value) return
  loadHistory(val)
})

async function send(text) {
  const content = (text ?? draft.value).trim()
  if (!content || loading.value) return
  draft.value = ''
  messages.value.push({ role: 'user', content })
  loading.value = true
  scrollToBottom()
  try {
    const res = await chatApi.send(content, bindProject.value)
    messages.value.push({ role: 'assistant', content: res.reply, trace: res.trace || [] })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `⚠️ 出错了：${e.message}` })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

// 实体引用跳转：任务/项目 chip → 打开所属项目看板
function gotoRef(ref) {
  const pid = ref.kind === 'project' ? ref.id : ref.project_id
  if (!pid) return ElMessage.warning('无法定位该项目，请手动切换')
  store.setCurrent(pid)
  router.push('/board')
}

// 一键演示：自动串起「建项目 → 绑定 → 规划任务 → 查任务」，展示多工具执行轨迹
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
    bindProject.value = p.id
    resetChat()
    const exist = await taskApi.list(p.id).catch(() => [])
    if (!exist.length) await send('帮我规划几个任务')
    await send('现在有哪些任务？')
    ElMessage.success('演示完成：已展示 Agent 建项目 + 规划 + 查询的执行轨迹，可展开上方步骤查看')
  } finally {
    demoBusy.value = false
  }
}

function resetChat() {
  messages.value = [] // 仅清空当前视图会话（绑定项目由选择器控制）
}

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  })
}

onMounted(async () => {
  if (!store.projects.length) await store.load()
  await loadHistory()
  scrollToBottom()
})
</script>

<style scoped>
.chat-page { display: flex; flex-direction: column; height: calc(100vh - 130px); }
.chat-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.hint { color: #909399; font-size: 13px; flex: 1; }
.guide { padding: 40px 24px 8px; }
.guide-title { font-size: 20px; font-weight: 700; color: #303133; text-align: center; }
.guide-sub { color: #909399; font-size: 13px; text-align: center; margin: 8px 0 18px; }
.guide-bullets { max-width: 540px; margin: 0 auto; padding-left: 20px; color: #606266; font-size: 13px; line-height: 2.1; }
.guide-actions { display: flex; justify-content: center; margin-top: 20px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 12px; }
.chip { cursor: pointer; }
.guide-note { margin-top: 16px; text-align: center; color: #b1b3b8; font-size: 12px; }
.msg-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 10px;
}
.typing { opacity: 0.7; }
.input-bar { display: flex; gap: 10px; margin-top: 12px; align-items: flex-end; }
.input-bar .el-textarea { flex: 1; }
</style>
