<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">记忆：会话事实与运维模式检索库（DB 不可用自动落内存）</div>
      <div>
        <el-button v-if="type === 'episodic'" type="primary" @click="openSave">手动保存</el-button>
        <el-button v-if="type === 'semantic'" type="primary" plain @click="openQuery">检索查询</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="type" @tab-change="load">
      <el-tab-pane label="episodic（会话事实）" name="episodic" />
      <el-tab-pane label="semantic（运维模式）" name="semantic" />
    </el-tabs>

    <el-table :data="items" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <template v-if="type === 'episodic'">
        <el-table-column prop="topic" label="主题" min-width="160" />
        <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
        <el-table-column prop="session_id" label="会话" width="140" />
      </template>
      <template v-else>
        <el-table-column prop="pattern" label="模式" min-width="180" show-overflow-tooltip />
        <el-table-column prop="trigger_condition" label="触发条件" min-width="240" show-overflow-tooltip />
        <el-table-column label="置信度" width="100">
          <template #default="{ row }">{{ (row.confidence * 100).toFixed(0) }}%</template>
        </el-table-column>
      </template>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="saveVisible" title="手动保存记忆" width="560px">
      <el-form label-width="90px">
        <el-form-item label="主题" required><el-input v-model="saveForm.topic" /></el-form-item>
        <el-form-item label="摘要"><el-input v-model="saveForm.summary" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="会话ID"><el-input v-model="saveForm.session_id" placeholder="可选" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" :title="type === 'episodic' ? '编辑记忆' : '编辑模式'" width="560px">
      <el-form label-width="100px">
        <template v-if="type === 'episodic'">
          <el-form-item label="主题"><el-input v-model="editForm.topic" /></el-form-item>
          <el-form-item label="摘要"><el-input v-model="editForm.summary" type="textarea" :rows="4" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="模式"><el-input v-model="editForm.pattern" /></el-form-item>
          <el-form-item label="触发条件"><el-input v-model="editForm.trigger_condition" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="置信度">
            <el-slider v-model="editForm.confidence" :min="0" :max="1" :step="0.1" show-input />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="queryVisible" title="记忆检索查询" width="600px">
      <el-input v-model="queryText" placeholder="输入查询关键词" @keyup.enter="handleQuery" />
      <div v-if="queryItems.length" class="query-list">
        <div v-for="q in queryItems" :key="q.id" class="query-item">
          <div class="query-topic">{{ q.topic }}</div>
          <div class="query-summary">{{ q.summary }}</div>
        </div>
      </div>
      <el-empty v-if="queried && !queryItems.length" description="未检索到记忆" />
      <template #footer>
        <el-button @click="queryVisible = false">关闭</el-button>
        <el-button type="primary" :loading="querying" @click="handleQuery">查询</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listMemory, saveMemory, editMemory, deleteMemory, queryMemory } from '../api/memory'

const type = ref('episodic')
const items = ref([])
const loading = ref(false)

const saveVisible = ref(false)
const saving = ref(false)
const saveForm = reactive({ topic: '', summary: '', session_id: '' })

const editVisible = ref(false)
const editForm = reactive({
  id: null, topic: '', summary: '',
  pattern: '', trigger_condition: '', confidence: 0.8
})

const queryVisible = ref(false)
const queryText = ref('')
const queryItems = ref([])
const queried = ref(false)
const querying = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = await listMemory({ type: type.value })
  } finally {
    loading.value = false
  }
}

function openSave() {
  Object.assign(saveForm, { topic: '', summary: '', session_id: '' })
  saveVisible.value = true
}

async function handleSave() {
  if (!saveForm.topic) {
    ElMessage.warning('主题必填')
    return
  }
  saving.value = true
  try {
    await saveMemory({ ...saveForm })
    ElMessage.success('已保存')
    saveVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

function openEdit(row) {
  editForm.id = row.id
  if (type.value === 'episodic') {
    Object.assign(editForm, { topic: row.topic || '', summary: row.summary || '', pattern: '', trigger_condition: '', confidence: 0.8 })
  } else {
    Object.assign(editForm, {
      topic: '', summary: '',
      pattern: row.pattern || '',
      trigger_condition: row.trigger_condition || '',
      confidence: row.confidence ?? 0.8
    })
  }
  editVisible.value = true
}

async function handleEdit() {
  saving.value = true
  try {
    const payload = type.value === 'episodic'
      ? { topic: editForm.topic, summary: editForm.summary }
      : { pattern: editForm.pattern, trigger_condition: editForm.trigger_condition, confidence: editForm.confidence }
    await editMemory(type.value, editForm.id, payload)
    ElMessage.success('已更新')
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm('删除该记忆？', '确认', { type: 'warning' })
  await deleteMemory(type.value, row.id)
  ElMessage.success('已删除')
  load()
}

function openQuery() {
  queryText.value = ''
  queryItems.value = []
  queried.value = false
  queryVisible.value = true
}

async function handleQuery() {
  if (!queryText.value.trim()) {
    ElMessage.warning('请输入查询关键词')
    return
  }
  querying.value = true
  try {
    queryItems.value = await queryMemory({ type: type.value, query: queryText.value.trim(), k: 5 })
    queried.value = true
  } finally {
    querying.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.page-hint {
  color: #606266;
  font-size: 13px;
}
.query-list {
  margin-top: 12px;
}
.query-item {
  padding: 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
  background: #f5f7fa;
}
.query-topic {
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}
.query-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}
</style>
