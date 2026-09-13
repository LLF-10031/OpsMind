<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">巡检脚本：编写/启用控制端下发脚本，配置跟踪指标与判定规则</div>
      <el-button type="primary" @click="openCreate">新增脚本</el-button>
    </div>

    <el-table :data="scripts" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
      <el-table-column label="内置" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" type="warning" size="small">内置</el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">
            {{ row.is_enabled ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="openRunTest(row)">试跑</el-button>
          <el-button size="small" @click="openPreviewLlm(row)">LLM预览</el-button>
          <el-button size="small" type="primary" plain @click="openMetrics(row)">指标</el-button>
          <el-button size="small" type="success" plain @click="openTrend(row)">趋势</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑脚本' : '新增脚本'" width="760px">
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：磁盘使用率检查" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" placeholder="可选" />
        </el-form-item>
        <el-form-item label="shell">
          <el-select v-model="form.shell" style="width: 120px">
            <el-option label="bash" value="bash" />
            <el-option label="sh" value="sh" />
          </el-select>
        </el-form-item>
        <el-form-item label="interpreter">
          <el-input v-model="form.interpreter" placeholder="如：bash" style="width: 120px" />
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="form.timeout" :min="1" :max="3600" />
        </el-form-item>
        <el-form-item label="脚本内容" required>
          <el-input v-model="form.content" type="textarea" :rows="12" :placeholder="`#!/bin/bash\n# 示例：df -h; echo 'usage 78%'`" class="mono" />
        </el-form-item>
        <el-form-item label="LLM判定规则">
          <el-input v-model="form.llm_rule_text" type="textarea" :rows="4" placeholder="可选：描述如何判定 warn/crit 与提取指标" class="mono" />
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

    <el-dialog v-model="runVisible" title="试运行脚本" width="620px">
      <el-form label-width="110px">
        <el-form-item label="选择主机" required>
          <el-select v-model="runHostId" style="width: 100%" placeholder="选择目标主机">
            <el-option v-for="h in hosts" :key="h.id" :label="h.name" :value="h.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div v-if="runResult" class="run-result">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="task_run_id">{{ runResult.task_run_id }}</el-descriptions-item>
          <el-descriptions-item label="run_id">{{ runResult.run_id }}</el-descriptions-item>
          <el-descriptions-item label="report_type">{{ runResult.report_type }}</el-descriptions-item>
          <el-descriptions-item label="level">{{ runResult.level }}</el-descriptions-item>
          <el-descriptions-item label="metrics">{{ JSON.stringify(runResult.metrics || {}) }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer>
        <el-button @click="runVisible = false">关闭</el-button>
        <el-button type="primary" :loading="running" @click="handleRun">执行</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="llmVisible" title="LLM 判定预览（不落库）" width="680px">
      <el-form label-width="110px">
        <el-form-item label="样例输出">
          <el-input v-model="llmSample" type="textarea" :rows="6" class="mono" placeholder="粘贴一段真实输出做预览" />
        </el-form-item>
        <el-form-item label="判定规则">
          <el-input v-model="llmRule" type="textarea" :rows="4" class="mono" placeholder="留空使用脚本已保存规则" />
        </el-form-item>
      </el-form>
      <div v-if="llmResult" class="run-result">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="level">{{ llmResult.level }}</el-descriptions-item>
          <el-descriptions-item label="reason">{{ llmResult.reason }}</el-descriptions-item>
          <el-descriptions-item label="metrics">{{ JSON.stringify(llmResult.metrics || {}) }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer>
        <el-button @click="llmVisible = false">关闭</el-button>
        <el-button type="primary" :loading="llmLoading" @click="handlePreviewLlm">预览</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="metricsVisible" title="跟踪指标" width="720px">
      <div class="metrics-add">
        <el-input v-model="metricForm.name" placeholder="指标名（如 disk_usage_percent）" style="width: 180px" />
        <el-select v-model="metricForm.extraction_mode" style="width: 130px">
          <el-option label="llm_regex" value="llm_regex" />
          <el-option label="regex" value="regex" />
          <el-option label="llm" value="llm" />
        </el-select>
        <el-input v-model="metricForm.regex_pattern" placeholder="正则，可选" style="width: 200px" class="mono" />
        <el-input v-model="metricForm.unit" placeholder="单位，可选" style="width: 80px" />
        <el-button type="primary" :loading="metricSaving" @click="addMetric">添加</el-button>
      </div>
      <el-table :data="metrics" size="small" border>
        <el-table-column prop="name" label="指标名" min-width="140" />
        <el-table-column prop="extraction_mode" label="模式" width="110" />
        <el-table-column prop="regex_pattern" label="正则" min-width="140" show-overflow-tooltip />
        <el-table-column prop="unit" label="单位" width="80" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.is_enabled" size="small" @change="(v) => toggleMetric(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="previewMetric(row)">预览值</el-button>
            <el-button size="small" type="danger" plain @click="deleteMetric(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="metricPreviewVisible" title="指标提取预览" width="560px">
      <el-input v-model="metricPreviewSample" type="textarea" :rows="6" placeholder="粘贴输出文本提取该指标" />
      <div v-if="metricPreviewResult" class="run-result">{{ JSON.stringify(metricPreviewResult) }}</div>
      <template #footer>
        <el-button @click="metricPreviewVisible = false">关闭</el-button>
        <el-button type="primary" :loading="metricPreviewLoading" @click="doMetricPreview">提取</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="trendVisible" title="指标趋势" width="860px">
      <div class="trend-bar">
        <el-select v-model="trendWindow" style="width: 120px" @change="loadTrend">
          <el-option :value="7" label="近 7 次" />
          <el-option :value="30" label="近 30 次" />
          <el-option :value="90" label="近 90 次" />
          <el-option :value="180" label="近 180 次" />
        </el-select>
        <el-select v-model="trendMetric" style="width: 200px" placeholder="全部指标" clearable @change="loadTrend">
          <el-option v-for="m in trendMetrics" :key="m.id" :label="m.name" :value="m.name" />
        </el-select>
        <el-button type="primary" plain :loading="trendSummaryLoading" @click="handleTrendSummary">生成趋势总结</el-button>
      </div>
      <div v-loading="trendLoading" class="trend-body">
        <div class="trend-section-title">状态历史</div>
        <el-table :data="trendData.history" size="small" border>
          <el-table-column prop="started_at" label="时间" min-width="170" />
          <el-table-column label="level" width="110">
            <template #default="{ row }"><LevelBadge v-if="row.level" :level="row.level" /></template>
          </el-table-column>
          <el-table-column prop="report_type" label="report_type" width="130" />
        </el-table>
        <template v-for="(points, key) in trendData.series" :key="key">
          <div class="trend-section-title">{{ key }}</div>
          <el-table :data="points" size="small" border>
            <el-table-column prop="ts" label="时间" min-width="170" />
            <el-table-column prop="value" label="值" min-width="120" />
            <el-table-column prop="source" label="来源" min-width="120" />
          </el-table>
        </template>
        <el-empty v-if="!trendData.history?.length && !trendLoading" description="暂无趋势数据" />
        <div v-if="trendSummary" class="trend-summary">{{ trendSummary }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listScripts, getScript, createScript, updateScript, deleteScript,
  runScript, previewScriptLlm,
  listTrackingMetrics, createTrackingMetric, toggleTrackingMetric,
  deleteTrackingMetric, previewTrackingMetric,
  getScriptTrend, generateTrendSummary
} from '../api/scripts'
import { listHosts } from '../api/hosts'
import LevelBadge from '../components/LevelBadge.vue'

const scripts = ref([])
const hosts = ref([])
const loading = ref(false)

const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({
  name: '', description: '', shell: 'bash', interpreter: 'bash',
  timeout: 30, content: '', llm_rule_text: '', is_enabled: true
})

const runVisible = ref(false)
const running = ref(false)
const runHostId = ref(null)
const runResult = ref(null)
const runScriptId = ref(null)

const llmVisible = ref(false)
const llmLoading = ref(false)
const llmSample = ref('')
const llmRule = ref('')
const llmResult = ref(null)
const llmScriptId = ref(null)

const metricsVisible = ref(false)
const metrics = ref([])
const metricSaving = ref(false)
const metricsScriptId = ref(null)
const metricForm = reactive({ name: '', extraction_mode: 'llm_regex', regex_pattern: '', unit: '' })

const metricPreviewVisible = ref(false)
const metricPreviewLoading = ref(false)
const metricPreviewSample = ref('')
const metricPreviewResult = ref(null)
const metricPreviewRow = ref(null)

const trendVisible = ref(false)
const trendLoading = ref(false)
const trendSummaryLoading = ref(false)
const trendScriptId = ref(null)
const trendWindow = ref(30)
const trendMetric = ref('')
const trendMetrics = ref([])
const trendData = ref({ history: [], series: {} })
const trendSummary = ref('')

async function load() {
  loading.value = true
  try {
    scripts.value = await listScripts()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    name: '', description: '', shell: 'bash', interpreter: 'bash',
    timeout: 30, content: '', llm_rule_text: '', is_enabled: true
  })
  dialogVisible.value = true
}

async function openEdit(row) {
  editing.value = row
  const detail = await getScriptById(row.id)
  Object.assign(form, {
    name: detail.name,
    description: row.description || '',
    shell: 'bash',
    interpreter: detail.interpreter || 'bash',
    timeout: detail.timeout,
    content: detail.content,
    llm_rule_text: typeof detail.llm_rule_text === 'string' ? detail.llm_rule_text : '',
    is_enabled: row.is_enabled
  })
  dialogVisible.value = true
}

async function getScriptById(id) {
  return await getScript(id)
}

async function handleSave() {
  if (!form.name || !form.content) {
    ElMessage.warning('名称与脚本内容必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const payload = {
        description: form.description,
        shell: form.shell,
        interpreter: form.interpreter,
        timeout: form.timeout,
        content: form.content,
        llm_rule_text: form.llm_rule_text,
        is_enabled: form.is_enabled
      }
      await updateScript(editing.value.id, payload)
    } else {
      await createScript({
        name: form.name,
        description: form.description,
        shell: form.shell,
        interpreter: form.interpreter,
        timeout: form.timeout,
        content: form.content,
        llm_rule_text: form.llm_rule_text,
        is_enabled: form.is_enabled
      })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`删除脚本「${row.name}」？`, '确认', { type: 'warning' })
  await deleteScript(row.id)
  ElMessage.success('已删除')
  load()
}

async function openRunTest(row) {
  runScriptId.value = row.id
  runResult.value = null
  if (!hosts.value.length) hosts.value = await listHosts()
  runVisible.value = true
}

async function handleRun() {
  if (!runHostId.value) {
    ElMessage.warning('请选择主机')
    return
  }
  running.value = true
  runResult.value = null
  try {
    runResult.value = await runScript(runScriptId.value, runHostId.value)
    ElMessage.success('执行完成')
  } finally {
    running.value = false
  }
}

function openPreviewLlm(row) {
  llmScriptId.value = row.id
  llmSample.value = ''
  llmRule.value = ''
  llmResult.value = null
  llmVisible.value = true
}

async function handlePreviewLlm() {
  llmLoading.value = true
  llmResult.value = null
  try {
    llmResult.value = await previewScriptLlm(llmScriptId.value, {
      sample_output: llmSample.value,
      llm_rule_text: llmRule.value
    })
  } finally {
    llmLoading.value = false
  }
}

async function openMetrics(row) {
  metricsScriptId.value = row.id
  metricsVisible.value = true
  loadMetrics(row.id)
}

async function loadMetrics(id) {
  metrics.value = await listTrackingMetrics(id)
}

async function addMetric() {
  if (!metricForm.name) {
    ElMessage.warning('指标名必填')
    return
  }
  metricSaving.value = true
  try {
    await createTrackingMetric(metricsScriptId.value, { ...metricForm })
    ElMessage.success('已添加')
    Object.assign(metricForm, { name: '', regex_pattern: '', unit: '' })
    loadMetrics(metricsScriptId.value)
  } finally {
    metricSaving.value = false
  }
}

async function toggleMetric(row, val) {
  try {
    await toggleTrackingMetric(row.id)
    row.is_enabled = val
  } catch {
    row.is_enabled = !val
  }
}

async function deleteMetric(row) {
  await ElMessageBox.confirm(`删除指标「${row.name}」？`, '确认', { type: 'warning' })
  await deleteTrackingMetric(row.id)
  ElMessage.success('已删除')
  loadMetrics(metricsScriptId.value)
}

function previewMetric(row) {
  metricPreviewRow.value = row
  metricPreviewSample.value = ''
  metricPreviewResult.value = null
  metricPreviewVisible.value = true
}

async function doMetricPreview() {
  metricPreviewLoading.value = true
  metricPreviewResult.value = null
  try {
    metricPreviewResult.value = await previewTrackingMetric(metricPreviewRow.value.id, {
      sample_output: metricPreviewSample.value
    })
    if (metricPreviewResult.value === null) metricPreviewResult.value = { note: '无结果' }
  } finally {
    metricPreviewLoading.value = false
  }
}

async function openTrend(row) {
  trendScriptId.value = row.id
  trendMetric.value = ''
  trendSummary.value = ''
  trendData.value = { history: [], series: {} }
  trendVisible.value = true
  try {
    trendMetrics.value = await listTrackingMetrics(row.id)
  } catch {
    trendMetrics.value = []
  }
  loadTrend()
}

async function loadTrend() {
  trendLoading.value = true
  try {
    trendData.value = await getScriptTrend(trendScriptId.value, {
      window: trendWindow.value,
      tracking_metric: trendMetric.value || undefined
    })
  } finally {
    trendLoading.value = false
  }
}

async function handleTrendSummary() {
  trendSummaryLoading.value = true
  trendSummary.value = ''
  try {
    const res = await generateTrendSummary(trendScriptId.value, {
      window: trendWindow.value,
      tracking_metric: trendMetric.value || undefined
    })
    trendSummary.value = res.summary || ''
  } catch {
    // 限流/失败已由拦截器提示
  } finally {
    trendSummaryLoading.value = false
  }
}

onMounted(() => {
  load()
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
.run-result {
  margin-top: 12px;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 10px;
}
.metrics-add {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.trend-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}
.trend-body {
  min-height: 120px;
}
.trend-section-title {
  font-weight: 600;
  margin: 14px 0 8px;
  color: #303133;
}
.trend-summary {
  margin-top: 16px;
  padding: 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
}
</style>
