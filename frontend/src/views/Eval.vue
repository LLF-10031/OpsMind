<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">评估：维护故障案例集，一键复用判定链路评估脚本质量</div>
      <div>
        <el-button type="primary" @click="openCreate">新建案例</el-button>
        <el-button type="success" plain :loading="running" @click="handleRun">运行评估</el-button>
      </div>
    </div>

    <el-card shadow="never" class="section-card">
      <div class="section-title">案例集</div>
      <el-table :data="cases" v-loading="loading" border stripe @selection-change="onSelectChange">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="标题" min-width="160" />
        <el-table-column label="预期级别" width="120">
          <template #default="{ row }"><LevelBadge v-if="row.expected_level" :level="row.expected_level" /></template>
        </el-table-column>
        <el-table-column label="标签" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="t in splitTags(row.tags)" :key="t" size="small" class="tag">{{ t }}</el-tag>
            <span v-if="!row.tags">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="handleDeleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="page-hint mt-8">勾选若干案例后「运行评估」只评估所选；不勾选则评估全部案例。</div>
    </el-card>

    <el-card v-if="runResults.length" shadow="never" class="section-card">
      <div class="section-title">本轮评估结果</div>
      <div class="agg-row">
        <span>命中率 <el-tag type="success">{{ pct(aggregate.hit_rate) }}</el-tag></span>
        <span>误报率 <el-tag type="danger">{{ pct(aggregate.false_positive) }}</el-tag></span>
        <span>报告质量 <el-tag type="warning">{{ pct(aggregate.quality) }}</el-tag></span>
      </div>
      <el-table :data="runResults" border stripe size="small">
        <el-table-column prop="case" label="案例ID" width="100" />
        <el-table-column label="级别命中" width="120">
          <template #default="{ row }">
            <el-tag :type="row.level_hit ? 'success' : 'danger'" size="small">{{ row.level_hit ? '命中' : '未命中' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="报告类型命中" width="130">
          <template #default="{ row }">
            <el-tag :type="row.rt_hit ? 'success' : 'danger'" size="small">{{ row.rt_hit ? '命中' : '未命中' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="得分" width="120">
          <template #default="{ row }">{{ (row.score * 100).toFixed(0) }}%</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="section-card">
      <div class="section-title">评估结果历史</div>
      <el-table :data="results" v-loading="resultsLoading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="run_id" label="run_id" width="110" />
        <el-table-column prop="case_id" label="案例ID" width="90" />
        <el-table-column label="实际级别" width="110">
          <template #default="{ row }"><LevelBadge v-if="row.actual_level" :level="row.actual_level" /></template>
        </el-table-column>
        <el-table-column prop="actual_report_type" label="报告类型" width="120" />
        <el-table-column label="级别命中" width="100">
          <template #default="{ row }">{{ row.level_hit ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="类型命中" width="100">
          <template #default="{ row }">{{ row.report_type_hit ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="得分" width="90">
          <template #default="{ row }">{{ (row.score * 100).toFixed(0) }}%</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="160" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createVisible" title="新建案例" width="640px">
      <el-form label-width="130px">
        <el-form-item label="标题" required><el-input v-model="caseForm.title" placeholder="如：磁盘写满报错判" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="caseForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="脚本内容"><el-input v-model="caseForm.script_content" type="textarea" :rows="6" class="mono" placeholder="故障复现脚本（exit 1/输出特征）" /></el-form-item>
        <el-form-item label="预期级别">
          <el-select v-model="caseForm.expected_level" style="width: 160px">
            <el-option label="ok" value="ok" />
            <el-option label="warn" value="warn" />
            <el-option label="crit" value="crit" />
          </el-select>
        </el-form-item>
        <el-form-item label="预期报告类型">
          <el-select v-model="caseForm.expected_report_type" style="width: 160px">
            <el-option label="success" value="success" />
            <el-option label="info" value="info" />
            <el-option label="report" value="report" />
            <el-option label="action_report" value="action_report" />
          </el-select>
        </el-form-item>
        <el-form-item label="判定依据 ground_truth"><el-input v-model="caseForm.ground_truth" type="textarea" :rows="3" class="mono" placeholder="做 LLM 第二关判定时的规则文本" /></el-form-item>
        <el-form-item label="标签"><el-input v-model="caseForm.tags" placeholder="逗号分隔，如：disk,failure" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleCreateCase">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="评估结果详情" width="620px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="run_id">{{ detail.run_id }}</el-descriptions-item>
          <el-descriptions-item label="case_id">{{ detail.case_id }}</el-descriptions-item>
          <el-descriptions-item label="实际级别">{{ detail.actual_level }}</el-descriptions-item>
          <el-descriptions-item label="报告类型">{{ detail.actual_report_type }}</el-descriptions-item>
          <el-descriptions-item label="级别命中">{{ detail.level_hit ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="类型命中">{{ detail.report_type_hit ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="得分">{{ (detail.score * 100).toFixed(0) }}%</el-descriptions-item>
          <el-descriptions-item label="时间">{{ detail.created_at }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="detail.radar" class="radar-block">
          <div v-for="(d, i) in detail.radar.dimensions" :key="d" class="radar-bar">
            <span class="radar-label">{{ d }}</span>
            <div class="radar-track">
              <div class="radar-fill" :style="{ width: pctWidth(detail.radar.values[i]) }"></div>
            </div>
            <span class="radar-value">{{ pct(detail.radar.values[i]) }}</span>
          </div>
        </div>
        <div v-if="detail.detail" class="detail-text">{{ detail.detail }}</div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import LevelBadge from '../components/LevelBadge.vue'
import {
  listEvalCases, createEvalCase, deleteEvalCase,
  runEval, listEvalResults, getEvalResult
} from '../api/eval'

const cases = ref([])
const loading = ref(false)
const selectedCaseIds = ref([])

const createVisible = ref(false)
const saving = ref(false)
const caseForm = reactive({
  title: '', description: '', script_content: '',
  expected_level: 'warn', expected_report_type: 'report',
  ground_truth: '', tags: ''
})

const running = ref(false)
const runResults = ref([])
const aggregate = ref({})

const results = ref([])
const resultsLoading = ref(false)

const detailVisible = ref(false)
const detail = ref(null)

function splitTags(tags) {
  if (!tags) return []
  return String(tags).split(',').map((s) => s.trim()).filter(Boolean)
}
function pct(v) {
  if (v === undefined || v === null) return '-'
  return `${(v * 100).toFixed(0)}%`
}
function pctWidth(v) {
  return `${Math.min(100, Math.max(0, (v || 0) * 100))}%`
}
function onSelectChange(rows) {
  selectedCaseIds.value = rows.map((r) => r.id)
}

async function loadCases() {
  loading.value = true
  try {
    cases.value = await listEvalCases()
  } finally {
    loading.value = false
  }
}

async function loadResults() {
  resultsLoading.value = true
  try {
    results.value = await listEvalResults({ limit: 100 })
  } finally {
    resultsLoading.value = false
  }
}

function openCreate() {
  Object.assign(caseForm, {
    title: '', description: '', script_content: '',
    expected_level: 'warn', expected_report_type: 'report',
    ground_truth: '', tags: ''
  })
  createVisible.value = true
}

async function handleCreateCase() {
  if (!caseForm.title) {
    ElMessage.warning('标题必填')
    return
  }
  saving.value = true
  try {
    await createEvalCase({ ...caseForm })
    ElMessage.success('已创建')
    createVisible.value = false
    loadCases()
  } finally {
    saving.value = false
  }
}

async function handleDeleteCase(row) {
  await ElMessageBox.confirm(`删除案例「${row.title}」？`, '确认', { type: 'warning' })
  await deleteEvalCase(row.id)
  ElMessage.success('已删除')
  loadCases()
}

async function handleRun() {
  if (!cases.value.length) {
    ElMessage.warning('暂无案例')
    return
  }
  running.value = true
  runResults.value = []
  aggregate.value = {}
  try {
    const res = await runEval({ case_ids: selectedCaseIds.value })
    runResults.value = res.results || []
    aggregate.value = res.aggregate || {}
    ElMessage.success('评估完成')
  } finally {
    running.value = false
  }
  loadResults()
}

async function openDetail(row) {
  detailVisible.value = true
  detail.value = null
  try {
    detail.value = await getEvalResult(row.id)
  } catch {
    detail.value = null
  }
}

onMounted(() => {
  loadCases()
  loadResults()
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
.mt-8 {
  margin-top: 8px;
}
.section-card {
  margin-bottom: 16px;
}
.section-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}
.tag {
  margin-right: 4px;
}
.agg-row {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #606266;
}
.radar-block {
  margin-top: 16px;
}
.radar-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.radar-label {
  width: 80px;
  color: #606266;
  font-size: 13px;
}
.radar-track {
  flex: 1;
  height: 14px;
  background: #f0f2f5;
  border-radius: 7px;
  overflow: hidden;
}
.radar-fill {
  height: 100%;
  background: linear-gradient(90deg, #409eff, #67c23a);
  border-radius: 7px;
  transition: width 0.3s;
}
.radar-value {
  width: 48px;
  text-align: right;
  color: #303133;
  font-size: 13px;
}
.detail-text {
  margin-top: 12px;
  padding: 10px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
}
.mono :deep(textarea) {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 13px;
}
</style>
