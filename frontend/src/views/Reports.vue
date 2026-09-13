<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">报告列表：全局浏览全部巡检与分析报告</div>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-form inline class="filter-bar">
      <el-form-item label="级别">
        <el-select v-model="filter.level" style="width: 130px" clearable @change="load">
          <el-option label="ok" value="ok" />
          <el-option label="warn" value="warn" />
          <el-option label="crit" value="crit" />
          <el-option label="unknown" value="unknown" />
        </el-select>
      </el-form-item>
      <el-form-item label="报告类型">
        <el-select v-model="filter.report_type" style="width: 150px" clearable @change="load">
          <el-option label="success" value="success" />
          <el-option label="info" value="info" />
          <el-option label="report" value="report" />
          <el-option label="action_report" value="action_report" />
          <el-option label="host_unreachable" value="host_unreachable" />
          <el-option label="timeout" value="timeout" />
          <el-option label="error" value="error" />
        </el-select>
      </el-form-item>
      <el-form-item label="脚本">
        <el-select v-model="filter.script_id" style="width: 200px" clearable @change="load">
          <el-option v-for="s in scripts" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
      </el-form-item>
    </el-form>

    <el-table :data="items" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="级别" width="110">
        <template #default="{ row }"><LevelBadge :level="row.level" /></template>
      </el-table-column>
      <el-table-column prop="report_type" label="报告类型" width="140" />
      <el-table-column label="脚本" width="140">
        <template #default="{ row }">{{ scriptName(row.script_id) }}</template>
      </el-table-column>
      <el-table-column prop="ai_content_preview" label="分析摘要" min-width="260" show-overflow-tooltip />
      <el-table-column prop="banner" label="标旗" width="160" show-overflow-tooltip />
      <el-table-column prop="created_at" label="时间" min-width="160" />
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="page-footer">
      <el-pagination
        v-model:current-page="page"
        :page-size="50"
        :total="total"
        layout="total, prev, pager, next"
        small
        @current-change="load"
      />
    </div>

    <el-dialog v-model="detailVisible" title="报告详情" width="720px">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="run_id">{{ detail.run_id }}</el-descriptions-item>
          <el-descriptions-item label="报告类型">{{ detail.report_type }}</el-descriptions-item>
          <el-descriptions-item label="AI 来源">{{ detail.ai_source }}</el-descriptions-item>
          <el-descriptions-item label="AI 状态">{{ detail.ai_status }}</el-descriptions-item>
          <el-descriptions-item label="标旗">{{ detail.banner || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="detail.meta" class="dlg-section">
          <div class="dlg-label">元信息</div>
          <pre class="report-pre">{{ JSON.stringify(detail.meta, null, 2) }}</pre>
        </div>
        <div class="dlg-section">
          <div class="dlg-label">AI 分析内容</div>
          <pre class="report-pre">{{ detail.ai_content || '（无）' }}</pre>
        </div>
        <div v-if="detail.annotations?.length" class="dlg-section">
          <div class="dlg-label">标注清单</div>
          <pre class="report-pre">{{ JSON.stringify(detail.annotations, null, 2) }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import LevelBadge from '../components/LevelBadge.vue'
import { listRuns, getRunReport } from '../api/runs'
import { listScripts } from '../api/scripts'

const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const scripts = ref([])
const scriptsMap = ref({})
const filter = reactive({ level: '', report_type: '', script_id: null })

const detailVisible = ref(false)
const detail = ref(null)

function scriptName(id) {
  const s = scriptsMap.value[id]
  return s ? s.name : (id ? `#${id}` : '-')
}

async function load() {
  loading.value = true
  try {
    const params = { limit: 50, offset: (page.value - 1) * 50 }
    if (filter.level) params.level = filter.level
    if (filter.report_type) params.report_type = filter.report_type
    if (filter.script_id) params.script_id = filter.script_id
    const res = await listRuns(params)
    items.value = res.items || []
    total.value = res.total || 0
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  detailVisible.value = true
  detail.value = null
  try {
    detail.value = await getRunReport(row.id)
  } catch {
    detail.value = null
  }
}

onMounted(async () => {
  try {
    const list = await listScripts()
    scripts.value = list
    scriptsMap.value = Object.fromEntries(list.map((s) => [s.id, s]))
  } catch {
    scripts.value = []
  }
  load()
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
.filter-bar {
  margin-bottom: 4px;
}
.page-footer {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
.dlg-section {
  margin-top: 14px;
}
.dlg-label {
  font-weight: 600;
  margin-bottom: 6px;
  color: #303133;
  font-size: 13px;
}
.report-pre {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 320px;
  overflow: auto;
}
</style>