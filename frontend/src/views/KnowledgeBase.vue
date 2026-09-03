<template>
  <div>
    <div class="toolbar">
      <el-select v-model="store.currentId" placeholder="选择项目" style="width: 260px" @change="loadDocs">
        <el-option v-for="p in store.projects" :key="p.id" :value="p.id" :label="p.name" />
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
          <el-icon :size="28" color="#409eff"><UploadFilled /></el-icon>
          <div class="upload-text">拖入或点击上传 .txt / .md 文档（UTF-8），自动进入知识库可被 Agent 检索</div>
        </div>
      </el-upload>
      <el-button type="primary" :icon="Upload" :loading="uploading" :disabled="!file" @click="doUpload">
        上传
      </el-button>
    </div>

    <el-card shadow="never" v-loading="loading">
      <el-table :data="docs" size="default" row-key="id">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="title" label="文档标题" min-width="200" />
        <el-table-column prop="file_type" label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ row.file_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="上传时间" width="180" />
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
      <el-empty v-if="!docs.length && !loading" description="该项目暂无知识库文档" :image-size="70" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, UploadFilled } from '@element-plus/icons-vue'
import { knowledgeApi } from '../api'
import { useProjectStore } from '../stores/project'

const store = useProjectStore()
const docs = ref([])
const loading = ref(false)
const uploading = ref(false)
const file = ref(null)

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

onMounted(async () => {
  if (!store.projects.length) await store.load()
  await loadDocs()
})
</script>

<style scoped>
.toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
.upload-text { color: #909399; font-size: 13px; line-height: 1.8; }
.doc-preview {
  white-space: pre-wrap;
  word-break: break-word;
  background: #fafafa;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
  max-height: 240px;
  overflow-y: auto;
}
</style>
