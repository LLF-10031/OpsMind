<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">巡检模板：编排脚本集合，支持对任意主机一键应用生成巡检任务</div>
      <el-button type="primary" @click="openCreate">新增模板</el-button>
    </div>

    <el-table :data="templates" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column label="内置" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" type="warning" size="small">内置</el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="schedule_json" label="调度配置" min-width="160" show-overflow-tooltip />
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="primary" plain @click="openApply(row)">应用</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑模板' : '新增模板'" width="640px">
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="绑定脚本" required>
          <el-select v-model="form.script_ids" multiple style="width: 100%" placeholder="选择脚本">
            <el-option v-for="s in scripts" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度 JSON">
          <el-input v-model="form.schedule_json" type="textarea" :rows="3" class="mono" placeholder='可选，如 {"cron":"0 */1 * * *"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="applyVisible" title="应用模板" width="560px">
      <el-alert type="info" :closable="false" show-icon
        title="选择一个目标主机，系统将按模板绑定脚本生成/更新该主机的巡检任务" />
      <el-form label-width="110px">
        <el-form-item label="目标主机">
          <el-select v-model="applyHostId" style="width: 100%" placeholder="选择主机">
            <el-option v-for="h in hosts" :key="h.id" :label="h.name" :value="h.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div v-if="applyResult" class="apply-result">
        已生成任务：{{ applyResult.task_id }}
      </div>
      <template #footer>
        <el-button @click="applyVisible = false">关闭</el-button>
        <el-button type="primary" :loading="applying" @click="handleApply">应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listTemplates, getTemplate, createTemplate, updateTemplate, deleteTemplate, applyTemplate
} from '../api/templates'
import { listScripts } from '../api/scripts'
import { listHosts } from '../api/hosts'

const templates = ref([])
const scripts = ref([])
const hosts = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({ name: '', description: '', script_ids: [], schedule_json: '' })

const applyVisible = ref(false)
const applying = ref(false)
const applyHostId = ref(null)
const applyResult = ref(null)
const applyTemplateId = ref(null)

async function load() {
  loading.value = true
  try {
    templates.value = await listTemplates()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', description: '', script_ids: [], schedule_json: '' })
  dialogVisible.value = true
}

async function openEdit(row) {
  editing.value = row
  const detail = await getTemplate(row.id)
  Object.assign(form, {
    name: detail.name,
    description: detail.description || '',
    script_ids: detail.script_ids?.map((s) => s.script_id) || [],
    schedule_json: typeof detail.schedule_json === 'string'
      ? detail.schedule_json
      : (JSON.stringify(detail.schedule_json || {}, null, 2))
  })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.name || !form.script_ids.length) {
    ElMessage.warning('名称与绑定脚本必填')
    return
  }
  let scheduleJson = null
  if (form.schedule_json && form.schedule_json.trim()) {
    try {
      scheduleJson = JSON.parse(form.schedule_json)
    } catch {
      ElMessage.warning('调度 JSON 格式不正确')
      return
    }
  }
  saving.value = true
  try {
    const payload = { description: form.description, script_ids: form.script_ids, schedule_json: scheduleJson }
    if (editing.value) {
      await updateTemplate(editing.value.id, payload)
    } else {
      await createTemplate({ name: form.name, ...payload })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`删除模板「${row.name}」？`, '确认', { type: 'warning' })
  await deleteTemplate(row.id)
  ElMessage.success('已删除')
  load()
}

function openApply(row) {
  applyTemplateId.value = row.id
  applyResult.value = null
  applyHostId.value = null
  applyVisible.value = true
}

async function handleApply() {
  if (!applyHostId.value) {
    ElMessage.warning('请选择目标主机')
    return
  }
  applying.value = true
  applyResult.value = null
  try {
    applyResult.value = await applyTemplate(applyTemplateId.value, applyHostId.value)
    ElMessage.success('应用成功')
  } finally {
    applying.value = false
  }
}

onMounted(() => {
  load()
  listScripts().then((s) => { scripts.value = s }).catch(() => {})
  listHosts().then((hs) => { hosts.value = hs }).catch(() => {})
})
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
.mono :deep(textarea) {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
}
.apply-result {
  margin-top: 12px;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 10px;
}
</style>
