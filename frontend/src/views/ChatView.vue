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

    <!-- 快捷示例 -->
    <div v-if="!messages.length" class="chips">
      <el-tag
        v-for="q in QUICK"
        :key="q"
        class="chip"
        effect="plain"
        @click="send(q)"
      >{{ q }}</el-tag>
    </div>

    <!-- 消息区 -->
    <div ref="scrollRef" class="msg-area">
      <el-empty v-if="!messages.length && !loading" description="用自然语言管理你的项目，例如：帮我创建一个项目…" :image-size="80" />
      <ChatMessage v-for="(m, i) in messages" :key="i" :role="m.role" :content="m.content" />
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
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Promotion, Refresh } from '@element-plus/icons-vue'
import { chatApi } from '../api'
import { useProjectStore } from '../stores/project'
import ChatMessage from '../components/ChatMessage.vue'

const store = useProjectStore()
const messages = ref([])
const draft = ref('')
const loading = ref(false)
const bindProject = ref(null)
const scrollRef = ref(null)

const QUICK = [
  '帮我创建「短视频运营」项目并自动规划任务',
  '查看我有哪些项目',
  '给电商系统项目加一个任务：上线前回归测试',
  '电商系统项目里有哪些营销工具？',
]

async function loadHistory() {
  try {
    const rows = await chatApi.history()
    messages.value = rows.map((r) => ({ role: r.role, content: r.content }))
  } catch { /* 历史加载失败忽略 */ }
}

async function send(text) {
  const content = (text ?? draft.value).trim()
  if (!content || loading.value) return
  draft.value = ''
  messages.value.push({ role: 'user', content })
  loading.value = true
  scrollToBottom()
  try {
    const res = await chatApi.send(content, bindProject.value)
    messages.value.push({ role: 'assistant', content: res.reply })
  } catch (e) {
    messages.value.push({ role: 'assistant', content: `⚠️ 出错了：${e.message}` })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function resetChat() {
  messages.value = []
  bindProject.value = null
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
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.chip { cursor: pointer; }
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
