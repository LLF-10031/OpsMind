<template>
  <div class="page">
    <div class="toolbar">
      <el-upload
        :show-file-list="false"
        accept=".md,.txt,.pdf"
        :http-request="handleUpload"
        :disabled="uploading"
      >
        <el-button type="primary" :loading="uploading">上传文档</el-button>
      </el-upload>
      <el-button @click="loadList">刷新</el-button>
      <el-tag type="info" size="small">仅支持 md / txt / pdf，上传即拆单元并向量化</el-tag>
    </div>

    <el-card shadow="never" class="search-card">
      <div class="search-bar">
        <el-input
          v-model="searchQuery"
          placeholder="输入检索词，回车搜索"
          style="flex: 1"
          clearable
          @keyup.enter="handleSearch"
        />
        <el-select
          v-model="searchDocIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="勾选文档限定范围"
          style="width: 260px"
        >
          <el-option v-for="d in docs" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-input-number v-model="searchK" :min="1" :max="30" controls-position="right" style="width: 110px" />
        <el-switch v-model="searchFullLibrary" active-text="搜全库" />
        <el-button type="primary" :loading="searching" @click="handleSearch">检索</el-button>
      </div>
      <div class="search-tip">未勾选文档且未开「搜全库」时不检索（勾选才查，与助手一致）</div>
      <div v-if="searchFormat" class="search-result">
        <div class="dlg-label">检索上下文</div>
        <pre class="norm-preview">{{ searchFormat }}</pre>
        <el-table v-if="searchResults.length" :data="searchResults" border stripe size="small" class="table">
          <el-table-column prop="doc_name" label="文档" min-width="140" show-overflow-tooltip />
          <el-table-column prop="parent_context" label="章节" min-width="140" show-overflow-tooltip />
          <el-table-column prop="value" label="内容" min-width="280" show-overflow-tooltip />
          <el-table-column label="来源" width="140">
            <template #default="{ row }">doc#{{ row.doc_id }} unit#{{ row.unit_id }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-table :data="docs" v-loading="loading" border stripe class="table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="文档名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="file_type" label="格式" width="90" />
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row.id)">详情</el-button>
          <el-button size="small" type="primary" plain @click="openFullText(row.id)">读全文</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="detailVisible" title="文档详情" width="720">
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="名称">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="格式">{{ detail.file_type }}</el-descriptions-item>
          <el-descriptions-item label="知识单元数">{{ detail.unit_count }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
        </el-descriptions>
        <div class="dlg-label">规范化内容</div>
        <pre class="norm-preview">{{ detail.normalized_md || '（无内容）' }}</pre>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" plain @click="openFullText(detail.id)">在线读全文</el-button>
        <el-button type="primary" @click="openUnits(detail.id)">查看单元</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="fullVisible" :title="`在线读全文 · ${fullText.name || ''}`" width="820" top="6vh">
      <el-tabs v-model="fullTab">
        <el-tab-pane label="规范化内容" name="normalized">
          <pre class="full-preview">{{ fullText.normalized_md || '（无内容）' }}</pre>
        </el-tab-pane>
        <el-tab-pane label="原始原文" name="raw">
          <pre class="full-preview">{{ fullText.raw_content || '（无原文）' }}</pre>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="fullVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unitsVisible" title="知识单元预览" width="720">
      <el-table :data="units" v-loading="unitsLoading" border stripe max-height="420">
        <el-table-column prop="unit_id" label="ID" width="70" />
        <el-table-column prop="kind" label="类型" width="80" />
        <el-table-column prop="path" label="路径" width="140" show-overflow-tooltip />
        <el-table-column prop="step_no" label="步骤" width="70" />
        <el-table-column prop="value" label="内容" min-width="280" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="unitsVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listDocuments, uploadDocument, getDocument, getDocumentContent, previewDocument, deleteDocument,
  searchDocuments
} from '../api/documents'

const docs = ref([])
const loading = ref(false)
const uploading = ref(false)
const detailVisible = ref(false)
const detail = ref(null)
const unitsVisible = ref(false)
const units = ref([])
const unitsLoading = ref(false)

const fullVisible = ref(false)
const fullTab = ref('normalized')
const fullText = ref({})

const searchQuery = ref('')
const searchDocIds = ref([])
const searchK = ref(6)
const searchFullLibrary = ref(false)
const searching = ref(false)
const searchFormat = ref('')
const searchResults = ref([])

async function loadList() {
  loading.value = true
  try {
    docs.value = await listDocuments()
  } catch (e) {
    ElMessage.error(e.message || '加载文档列表失败')
  } finally {
    loading.value = false
  }
}

async function handleUpload(options) {
  uploading.value = true
  try {
    await uploadDocument(options.file)
    ElMessage.success('上传成功，已入库并向量化')
    loadList()
    if (typeof options.onSuccess === 'function') options.onSuccess()
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
    if (typeof options.onError === 'function') options.onError(e)
  } finally {
    uploading.value = false
  }
}

async function openDetail(id) {
  detail.value = null
  detailVisible.value = true
  try {
    detail.value = await getDocument(id)
  } catch (e) {
    ElMessage.error(e.message || '加载详情失败')
  }
}

async function openUnits(id) {
  unitsVisible.value = true
  unitsLoading.value = true
  try {
    units.value = await previewDocument(id)
  } catch (e) {
    ElMessage.error(e.message || '加载单元失败')
  } finally {
    unitsLoading.value = false
  }
}

async function openFullText(id) {
  fullVisible.value = true
  fullTab.value = 'normalized'
  fullText.value = {}
  try {
    fullText.value = await getDocumentContent(id)
  } catch (e) {
    ElMessage.error(e.message || '加载全文失败')
  }
}

async function handleSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    ElMessage.warning('请输入检索词')
    return
  }
  searching.value = true
  searchFormat.value = ''
  searchResults.value = []
  try {
    const res = await searchDocuments(q, {
      document_ids: searchFullLibrary.value ? undefined : searchDocIds.value,
      full_library: searchFullLibrary.value,
      k: searchK.value
    })
    searchFormat.value = res.format || ''
    searchResults.value = res.results || []
  } catch {
    // SEARCH_FAILED 已由拦截器提示
  } finally {
    searching.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`删除文档「${row.name}」？`, '确认', { type: 'warning' })
  try {
    await deleteDocument(row.id)
    ElMessage.success('已删除')
    if (detail.value && detail.value.id === row.id) detailVisible.value = false
    loadList()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

onMounted(loadList)
</script>

<style scoped>
.page {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.table {
  width: 100%;
}
.dlg-label {
  margin-top: 14px;
  margin-bottom: 6px;
  font-size: 13px;
  color: #606266;
}
.norm-preview {
  max-height: 240px;
  overflow: auto;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}
.full-preview {
  max-height: 62vh;
  overflow: auto;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}
.search-card {
  margin-bottom: 14px;
}
.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.search-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.search-result {
  margin-top: 12px;
}
</style>
