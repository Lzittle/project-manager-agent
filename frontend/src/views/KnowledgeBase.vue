<template>
  <div>
    <div class="toolbar">
      <el-select v-model="store.currentId" placeholder="选择项目" style="width: 260px" @change="loadDocs">
        <el-option
          v-for="row in store.treeRows"
          :key="row.id"
          :value="row.id"
          :label="(row.depth > 1 ? '\u3000'.repeat(row.depth - 1) + '└ ' : '') + row.name"
        />
      </el-select>
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept=".txt,.md"
        :on-change="onFileChange"
        style="flex: 1"
      >
        <div style="padding: 8px 0">
          <el-icon :size="28" color="var(--el-color-primary)"><UploadFilled /></el-icon>
          <div class="upload-text">拖入或点击上传 .txt / .md 文档（UTF-8），自动进入知识库可被 Agent 检索</div>
        </div>
      </el-upload>
      <el-button type="primary" :icon="Upload" :loading="uploading" :disabled="!file" @click="doUpload">
        上传
      </el-button>
      <el-button type="primary" plain :icon="DocumentAdd" @click="openMeetingDlg">
        录入会议纪要
      </el-button>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-table :data="docs" size="default" row-key="id">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.doc_type === 'meeting'" type="warning" effect="light" size="small">
              纪要
            </el-tag>
            <el-tag v-else size="small" type="info" effect="plain">{{ row.file_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="录入时间" width="180" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeDoc(row)">删除</el-button>
          </template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre class="doc-preview">{{ row.content }}</pre>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!docs.length && !loading" description="该项目暂无知识库内容，可上传文档或录入会议纪要" :image-size="70" />
    </el-card>

    <!-- 录入会议纪要对话框：正文直接入库并向量化，供 Agent 长期记忆检索 -->
    <el-dialog v-model="meetingDlg" title="录入会议纪要（项目长期记忆）" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="纪要主题" required>
          <el-input v-model="meetingTitle" maxlength="200" show-word-limit
                    placeholder="如：2026-09-08 迭代评审" />
        </el-form-item>
        <el-form-item label="纪要正文" required>
          <el-input v-model="meetingContent" type="textarea" :rows="9" maxlength="5000"
                    show-word-limit placeholder="粘贴或输入会议要点：结论、决策、待办、风险…（入库后可被 Agent 检索）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="meetingDlg = false">取消</el-button>
        <el-button type="primary" :loading="savingMeeting" @click="submitMeeting">保存入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, UploadFilled, DocumentAdd } from '@element-plus/icons-vue'
import { knowledgeApi } from '../api'
import { useProjectStore } from '../stores/project'

const store = useProjectStore()
const docs = ref([])
const loading = ref(false)
const uploading = ref(false)
const file = ref(null)
const meetingDlg = ref(false)
const meetingTitle = ref('')
const meetingContent = ref('')
const savingMeeting = ref(false)

async function loadDocs() {
  if (!store.currentId) { docs.value = []; return }
  loading.value = true
  try {
    docs.value = await knowledgeApi.list(store.currentId)
  } catch (e) { ElMessage.error(e.message) }
  finally { loading.value = false }
}

function onFileChange(f) {
  file.value = f.raw
}

async function doUpload() {
  if (!file.value) return ElMessage.warning('请先选择文件')
  uploading.value = true
  try {
    await knowledgeApi.upload(store.currentId, file.value)
    ElMessage.success('上传成功，已入库并向量化')
    file.value = null
    await loadDocs()
  } catch (e) {
    ElMessage.error('上传失败：' + e.message)
  } finally {
    uploading.value = false
  }
}

async function removeDoc(row) {
  try {
    await ElMessageBox.confirm(`确认删除文档「${row.title}」？其向量数据将一并清理。`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await knowledgeApi.remove(row.id)
    ElMessage.success('已删除')
    await loadDocs()
  } catch (e) { ElMessage.error(e.message) }
}

function openMeetingDlg() {
  if (!store.currentId) {
    ElMessage.warning('请先选择要归档纪要的项目')
    return
  }
  meetingDlg.value = true
}

async function submitMeeting() {
  const title = meetingTitle.value.trim()
  const content = meetingContent.value.trim()
  if (!title) return ElMessage.warning('请填写纪要主题')
  if (!content) return ElMessage.warning('请填写纪要正文')
  savingMeeting.value = true
  try {
    const doc = await knowledgeApi.meeting(store.currentId, title, content)
    ElMessage.success(`纪要「${doc.title}」已入库并向量化，Agent 后续可自动检索`)
    meetingDlg.value = false
    meetingTitle.value = ''
    meetingContent.value = ''
    await loadDocs()
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    savingMeeting.value = false
  }
}

onMounted(async () => {
  if (!store.projects.length) await store.load()
  await loadDocs()
})
</script>

<style scoped>
.toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
.upload-text { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.8; }
.doc-preview {
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-lighter);
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
  max-height: 240px;
  overflow-y: auto;
}
</style>
