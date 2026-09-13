<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">巡检任务：每个任务归属单台主机，可绑定多个脚本并按调度执行</div>
      <el-button type="primary" @click="openCreate">新增任务</el-button>
    </div>

    <el-form class="host-filter" inline>
      <el-form-item label="主机">
        <el-select v-model="selectedHostId" style="width: 260px" placeholder="选择主机查看其任务" clearable @change="loadTasks">
          <el-option v-for="h in hosts" :key="h.id" :label="h.name" :value="h.id" />
        </el-select>
      </el-form-item>
    </el-form>

    <el-table :data="tasks" v-loading="loading" border stripe empty-text="请选择主机查看任务">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
      <el-table-column label="调度配置" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ formatSchedule(row.schedule_json) }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.is_enabled" @change="(v) => toggleTask(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="primary" plain @click="handleRun(row)">立即执行</el-button>
          <el-button size="small" @click="openHistory(row)">历史</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑任务' : '新增任务'" width="640px">
      <el-form label-width="110px">
        <el-form-item label="主机" required>
          <el-select v-model="form.host_id" style="width: 100%" :disabled="!!editing" placeholder="选择主机">
            <el-option v-for="h in hosts" :key="h.id" :label="h.name" :value="h.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：每日基础巡检" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="绑定脚本">
          <el-select v-model="form.script_ids" multiple style="width: 100%" placeholder="可选，不选则执行空脚本">
            <el-option v-for="s in scripts" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度方式">
          <el-radio-group v-model="form.schedule_mode">
            <el-radio-button label="none">仅手动</el-radio-button>
            <el-radio-button label="interval">按间隔</el-radio-button>
            <el-radio-button label="cron">按 Cron</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.schedule_mode === 'interval'" label="间隔(分钟)">
          <el-input-number v-model="form.interval_minutes" :min="1" :max="10080" />
          <span class="sched-tip">如 5 = 每 5 分钟执行一次</span>
        </el-form-item>
        <el-form-item v-if="form.schedule_mode === 'cron'" label="Cron 表达式">
          <el-input v-model="form.cron_expr" placeholder="分 时 日 月 周，如 0 3 * * *" />
          <div class="sched-presets">
            <el-button v-for="p in cronPresets" :key="p.value" size="small" link type="primary"
              @click="form.cron_expr = p.value">{{ p.label }}</el-button>
          </div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="执行历史" width="600px">
      <el-table :data="runs" v-loading="historyLoading" size="small" border>
        <el-table-column prop="id" label="Run ID" width="90" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="trigger" label="触发方式" width="110" />
        <el-table-column prop="started_at" label="开始时间" min-width="150" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="goBoard(row.id)">看板</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listHosts, listHostTasks } from '../api/hosts'
import { createTask, getTask, updateTask, deleteTask, toggleTask, runTask, listTaskRuns } from '../api/tasks'
import { listScripts } from '../api/scripts'

const router = useRouter()
const hosts = ref([])
const scripts = ref([])
const selectedHostId = ref(null)
const tasks = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({
  host_id: null, name: '', description: '', script_ids: [],
  schedule_mode: 'none', interval_minutes: 5, cron_expr: '0 3 * * *', is_enabled: true
})

const cronPresets = [
  { label: '每5分钟', value: '*/5 * * * *' },
  { label: '每小时', value: '0 * * * *' },
  { label: '每天3点', value: '0 3 * * *' },
  { label: '每周一3点', value: '0 3 * * 1' },
]

const historyVisible = ref(false)
const historyLoading = ref(false)
const runs = ref([])
const historyTaskId = ref(null)

async function loadHosts() {
  hosts.value = await listHosts()
}

async function loadTasks() {
  tasks.value = []
  if (!selectedHostId.value) return
  loading.value = true
  try {
    tasks.value = await listHostTasks(selectedHostId.value)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    host_id: selectedHostId.value, name: '', description: '', script_ids: [],
    schedule_mode: 'none', interval_minutes: 5, cron_expr: '0 3 * * *', is_enabled: true
  })
  dialogVisible.value = true
}

async function openEdit(row) {
  editing.value = row
  const detail = await getTask(row.id)
  const sched = detail.schedule_json
  let mode = 'none'
  let minutes = 5
  let cron = '0 3 * * *'
  if (sched && typeof sched === 'object') {
    if (sched.type === 'interval') { mode = 'interval'; minutes = Number(sched.value) || 5 }
    else if (sched.type === 'cron') { mode = 'cron'; cron = String(sched.value || '0 3 * * *') }
  }
  Object.assign(form, {
    host_id: detail.host_id,
    name: detail.name,
    description: detail.description || '',
    script_ids: detail.script_ids || [],
    schedule_mode: mode,
    interval_minutes: minutes,
    cron_expr: cron,
    is_enabled: detail.is_enabled
  })
  dialogVisible.value = true
}

function buildSchedule() {
  if (form.schedule_mode === 'none') return null
  if (form.schedule_mode === 'interval') {
    const m = Number(form.interval_minutes)
    if (!m || m <= 0) {
      ElMessage.warning('间隔需为正整数分钟')
      return undefined
    }
    return { type: 'interval', value: m }
  }
  const expr = (form.cron_expr || '').trim()
  if (!expr) {
    ElMessage.warning('请填写 Cron 表达式')
    return undefined
  }
  return { type: 'cron', value: expr }
}

async function handleSave() {
  if (!form.host_id || !form.name) {
    ElMessage.warning('主机与名称必填')
    return
  }
  const schedule = buildSchedule()
  if (schedule === undefined) return
  saving.value = true
  try {
    const base = { description: form.description, schedule_json: schedule, is_enabled: form.is_enabled }
    if (editing.value) {
      await updateTask(editing.value.id, { ...base, name: form.name, ...(form.script_ids.length ? { script_ids: form.script_ids } : {}) })
    } else {
      await createTask({ host_id: form.host_id, name: form.name, ...base, ...(form.script_ids.length ? { script_ids: form.script_ids } : {}) })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    loadTasks()
  } finally {
    saving.value = false
  }
}

async function toggleRow(row, val) {
  try {
    await toggleTask(row.id, val)
    row.is_enabled = val
  } catch {
    row.is_enabled = !val
  }
}

async function handleRun(row) {
  const res = await runTask(row.id)
  ElMessage.success('已触发执行')
  goBoard(res.task_run_id)
}

function formatSchedule(sched) {
  if (!sched || typeof sched !== 'object') return '仅手动'
  if (sched.type === 'interval') return `每 ${sched.value} 分钟`
  if (sched.type === 'cron') return `Cron: ${sched.value}`
  return '仅手动'
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`删除任务「${row.name}」？`, '确认', { type: 'warning' })
  await deleteTask(row.id)
  ElMessage.success('已删除')
  loadTasks()
}

async function openHistory(row) {
  historyTaskId.value = row.id
  historyVisible.value = true
  historyLoading.value = true
  try {
    runs.value = await listTaskRuns(row.id)
  } finally {
    historyLoading.value = false
  }
}

function statusType(status) {
  if (status === 'running') return 'warning'
  if (status === 'success') return 'success'
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'error') return 'danger'
  return 'info'
}

function goBoard(runId) {
  historyVisible.value = false
  router.push(`/task-runs/${runId}`)
}

onMounted(() => {
  loadHosts().then(() => {
    if (hosts.value.length && !selectedHostId.value) {
      selectedHostId.value = hosts.value[0].id
      loadTasks()
    }
  }).catch(() => {})
  listScripts().then((s) => { scripts.value = s }).catch(() => {})
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
.host-filter {
  margin-bottom: 4px;
}
.mono :deep(textarea) {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
}
.sched-tip {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}
.sched-presets {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
