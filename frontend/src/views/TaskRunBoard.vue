<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">
        <el-button link type="primary" @click="$router.back()">返回</el-button>
        巡检看板 · TaskRun #{{ taskRunId }}
        <el-tag size="small" :type="statusTagType" class="ml-8">{{ taskRun.status }}</el-tag>
        <span class="ml-8">触发：{{ taskRun.trigger || '-' }}</span>
        <span class="ml-8">开始：{{ taskRun.started_at || '-' }}</span>
        <el-tag size="small" :type="streamTag.type" class="ml-8">{{ streamTag.text }}</el-tag>
      </div>
      <div>
        <el-button v-if="taskRun.status === 'RUNNING'" size="small" type="danger" :loading="cancelling" @click="handleCancel">停止</el-button>
        <el-button size="small" :loading="loading" @click="fullReload">刷新</el-button>
      </div>
    </div>

    <template v-if="summaryKeys.length">
      <div class="batch-bar">
        <span class="batch-label">批次汇总</span>
        <el-tag v-for="k in summaryKeys" :key="k" size="small" :type="summaryTagType(k)">
          {{ k }} × {{ taskRun.summary_json[k] }}
        </el-tag>
      </div>
    </template>

    <div v-loading="loading" class="runs-wrap">
      <div v-for="r in runs" :key="r.run_id" class="run-item" :class="{ 'is-running': r.status === 'running' }">
        <div class="run-head">
          <span class="run-name">{{ scriptName(r.script_id) }}</span>
          <span class="run-id">run#{{ r.run_id }}</span>
          <LevelBadge v-if="r.level" :level="r.level" />
          <el-tag v-if="r.report_type" size="small" type="info">{{ r.report_type }}</el-tag>
          <span v-if="r.duration_ms" class="run-meta">{{ (r.duration_ms / 1000).toFixed(2) }}s</span>
          <span v-if="r.exit_code !== undefined && r.exit_code !== null" class="run-meta">exit={{ r.exit_code }}</span>
          <el-tag v-if="r.status === 'running'" size="small" type="warning" effect="dark" class="ml-8">分析中…</el-tag>
          <span class="run-actions">
            <el-button size="small" link type="primary" @click="openOutput(r)">原始输出</el-button>
            <el-button size="small" link type="warning" @click="reanalyze(r)">重新分析</el-button>
          </span>
        </div>
        <ReportCard v-if="r.report" :report="r.report" :run="r" />
        <div v-else class="run-no-report">报告生成中，请等待…</div>
      </div>
      <el-empty v-if="!runs.length && !loading" description="暂无 run，等待执行推送…" />
    </div>

    <el-dialog v-model="outputVisible" title="原始输出" width="760px">
      <div class="output-bar">
        <el-input v-model="outputKeyword" placeholder="关键词过滤" class="kw-input" size="small" />
        <el-button size="small" type="primary" @click="loadOutput">读取</el-button>
      </div>
      <div class="output-meta" v-if="outputInfo">共 {{ outputInfo.lines }} 行</div>
      <pre class="output-pre">{{ outputContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import LevelBadge from '../components/LevelBadge.vue'
import ReportCard from '../components/ReportCard.vue'
import { getTaskRun, listRunsOfTaskRun, streamUrl, cancelTaskRun } from '../api/taskRuns'
import { getRun, getRunReport, getRunOutput, reanalyzeRun } from '../api/runs'
import { listScripts } from '../api/scripts'

const route = useRoute()
const taskRunId = Number(route.params.id)

const loading = ref(false)
const cancelling = ref(false)
const taskRun = reactive({ status: '', trigger: '', started_at: '', summary_json: {} })
const runs = ref([])
const streamState = ref('init') // init | connecting | connected | done | error
const scriptsMap = ref({})

const outputVisible = ref(false)
const outputKeyword = ref('')
const outputContent = ref('')
const outputInfo = ref(null)

const streamTag = computed(() => {
  switch (streamState.value) {
    case 'connected': return { type: 'success', text: '实时连接中' }
    case 'done': return { type: 'info', text: '已完成' }
    case 'error': return { type: 'danger', text: '连接异常' }
    default: return { type: 'warning', text: '连接中…' }
  }
})

const statusTagType = computed(() => {
  if (taskRun.status === 'RUNNING') return 'warning'
  if (taskRun.status === 'DONE' || taskRun.status === 'COMPLETED') return 'success'
  if (taskRun.status === 'FAILED') return 'danger'
  return 'info'
})

const summaryKeys = computed(() => Object.keys(taskRun.summary_json || {}))
function summaryTagType(type) {
  if (type === 'success' || type === 'ok') return 'success'
  if (type === 'warn') return 'warning'
  if (type === 'crit' || type === 'error') return 'danger'
  return 'info'
}

function scriptName(id) {
  const s = scriptsMap.value[id]
  return s ? s.name : (id ? `脚本 #${id}` : '-')
}

let fs = null
let closedNormally = false
let errorCount = 0
let fallbackTimer = null

function findRun(runId) {
  return runs.value.find((r) => r.run_id === runId)
}

function upsertRun(meta) {
  let r = findRun(meta.run_id)
  if (!r) {
    r = Object.assign({ run_id: meta.run_id, script_id: meta.script_id, report_type: meta.report_type, level: meta.level, status: 'done' }, meta)
    runs.value.push(r)
  } else {
    Object.assign(r, meta, { status: 'done' })
  }
  return r
}

async function loadRunDetail(runId) {
  const r = findRun(runId)
  if (!r) return
  try {
    r.detail = await getRun(runId)
    Object.assign(r, {
      exit_code: r.detail.exit_code,
      duration_ms: r.detail.duration_ms,
      output_path: r.detail.output_path
    })
  } catch { /* ignore */ }
  try {
    r.report = await getRunReport(runId)
  } catch {
    r.report = null
  }
}

async function fullReload() {
  loading.value = true
  try {
    const detail = await getTaskRun(taskRunId)
    Object.assign(taskRun, detail)
    const list = await listRunsOfTaskRun(taskRunId)
    const byId = {}
    for (const r of list) byId[r.run_id] = r
    const current = {}
    for (const r of runs.value) current[r.run_id] = r
    for (const r of list) {
      if (current[r.run_id]) Object.assign(current[r.run_id], r, { status: 'done' })
      else runs.value = [...runs.value, Object.assign({ status: 'done' }, r)]
    }
    for (const key of Object.keys(byId)) await loadRunDetail(key)
  } finally {
    loading.value = false
  }
}

function scheduleFallback() {
  // 流异常/事件丢失时兜底一次 REST 全量刷新（节流：3s 内只触发一次）
  if (fallbackTimer) return
  fallbackTimer = setTimeout(async () => {
    fallbackTimer = null
    await fullReload()
  }, 3000)
}

function connectStream() {
  if (fs) fs.close()
  closedNormally = false
  errorCount = 0
  streamState.value = 'connecting'
  fs = new EventSource(streamUrl(taskRunId))
  fs.onopen = () => {
    streamState.value = 'connected'
    errorCount = 0
  }
  fs.addEventListener('run_result', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      const r = upsertRun(data)
      loadRunDetail(r.run_id)
    } catch { /* ignore */ }
  })
  fs.addEventListener('batch_ready', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      taskRun.summary_json = data.summary || {}
    } catch { /* ignore */ }
  })
  fs.addEventListener('done', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      taskRun.status = data && data.cancelled ? 'CANCELLED' : 'DONE'
    } catch {
      taskRun.status = 'DONE'
    }
    streamState.value = 'done'
    closedNormally = true
    fs.close()
    fullReload()
  })
  fs.addEventListener('error', (ev) => {
    try {
      const data = JSON.parse(ev.data)
      ElMessage.error(data.message || '流异常')
    } catch { /* ignore */ }
  })
  fs.onerror = () => {
    if (closedNormally) return
    errorCount += 1
    streamState.value = errorCount > 2 ? 'error' : 'connecting'
    scheduleFallback()
  }
}

function openOutput(r) {
  outputVisible.value = true
  outputContent.value = ''
  outputInfo.value = null
  outputKeyword.value = ''
  currentOutputRun = r
  loadOutput()
}
let currentOutputRun = null

async function loadOutput() {
  if (!currentOutputRun) return
  try {
    const res = await getRunOutput(currentOutputRun.run_id, { keyword: outputKeyword.value || undefined, limit: 500 })
    outputContent.value = res.content
    outputInfo.value = { lines: res.lines }
  } catch (e) {
    ElMessage.error(e.message || '读取输出失败')
  }
}

async function reanalyze(r) {
  try {
    await reanalyzeRun(r.run_id, {})
    ElMessage.success('已触发重新分析')
    loadRunDetail(r.run_id)
  } catch (e) {
    ElMessage.error(e.message || '重新分析失败')
  }
}

async function handleCancel() {
  try {
    await ElMessageBox.confirm('确认停止该巡检批次？当前脚本结束后中止。', '停止', { type: 'warning' })
  } catch {
    return
  }
  cancelling.value = true
  try {
    await cancelTaskRun(taskRunId)
    ElMessage.info('已请求停止，等待当前脚本结束')
  } catch {
    // NOT_RUNNING 已由拦截器提示
  } finally {
    cancelling.value = false
  }
}

onMounted(async () => {
  runs.value = []
  listScripts().then((list) => {
    scriptsMap.value = Object.fromEntries(list.map((s) => [s.id, s]))
  }).catch(() => {})
  await fullReload()
  if (taskRun.status === 'RUNNING') connectStream()
})

onBeforeUnmount(() => {
  if (fs) fs.close()
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
.ml-8 {
  margin-left: 8px;
}
.batch-bar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.batch-label {
  color: #606266;
  font-size: 13px;
}
.runs-wrap {
  min-height: 120px;
}
.run-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: #fff;
}
.run-item.is-running {
  border-color: #e6a23c;
}
.run-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.run-name {
  font-weight: 600;
}
.run-id, .run-meta {
  color: #909399;
  font-size: 12px;
}
.run-actions {
  margin-left: auto;
}
.run-no-report {
  color: #909399;
  font-size: 13px;
  padding: 12px 0;
}
.output-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.kw-input {
  flex: 1;
}
.output-meta {
  color: #909399;
  font-size: 12px;
  margin-bottom: 6px;
}
.output-pre {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  max-height: 480px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
