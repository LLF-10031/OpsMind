<template>
  <div v-loading="loading">
    <div class="stat-cards">
      <el-card shadow="hover" class="stat-card" @click="$router.push('/hosts')">
        <div class="stat-num">{{ data.hosts?.total ?? '-' }}</div>
        <div class="stat-label">主机（可达 {{ data.hosts?.reachable ?? '-' }}）</div>
      </el-card>
      <el-card shadow="hover" class="stat-card" @click="$router.push('/tasks')">
        <div class="stat-num">{{ data.tasks_enabled ?? '-' }}</div>
        <div class="stat-label">启用任务</div>
      </el-card>
      <el-card shadow="hover" class="stat-card" @click="$router.push('/scripts')">
        <div class="stat-num">{{ data.scripts_enabled ?? '-' }}</div>
        <div class="stat-label">启用脚本</div>
      </el-card>
      <el-card shadow="hover" class="stat-card" @click="$router.push('/documents')">
        <div class="stat-num">{{ data.docs_total ?? '-' }}</div>
        <div class="stat-label">知识库文档</div>
      </el-card>
    </div>

    <el-card shadow="never" class="section-card">
      <div class="section-title">报告级别分布</div>
      <div v-if="levelEntries.length" class="level-row">
        <el-tag v-for="[lvl, n] in levelEntries" :key="lvl" :type="levelTagType(lvl)" size="large" class="level-tag">
          {{ lvl }} × {{ n }}
        </el-tag>
      </div>
      <el-empty v-else description="暂无 run 数据" :image-size="60" />
    </el-card>

    <el-card shadow="never" class="section-card">
      <div class="section-title">近期巡检批次</div>
      <el-table :data="data.recent_task_runs" border stripe size="small">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="任务" width="100">
          <template #default="{ row }">{{ row.task_id ? `#${row.task_id}` : '试跑' }}</template>
        </el-table-column>
        <el-table-column prop="trigger" label="触发" width="100" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="runStatusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始" min-width="160" />
        <el-table-column label="汇总">
          <template #default="{ row }">
            <el-tag v-for="k in Object.keys(row.summary_json || {})" :key="k" size="small" :type="summaryType(k)" class="tag">
              {{ k }} × {{ row.summary_json[k] }}
            </el-tag>
            <span v-if="!Object.keys(row.summary_json || {}).length">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="$router.push(`/task-runs/${row.id}`)">看板</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!data.recent_task_runs?.length && !loading" description="暂无巡检批次" :image-size="60" />
    </el-card>

    <el-card shadow="never" class="section-card">
      <div class="section-title">近期告警（crit / warn）</div>
      <el-table :data="data.recent_alerts" border stripe size="small">
        <el-table-column prop="id" label="Run ID" width="90" />
        <el-table-column prop="task_run_id" label="批次" width="100" />
        <el-table-column prop="script_id" label="脚本ID" width="90" />
        <el-table-column label="级别" width="100">
          <template #default="{ row }"><LevelBadge :level="row.level" /></template>
        </el-table-column>
        <el-table-column prop="report_type" label="报告类型" width="130" />
        <el-table-column prop="created_at" label="时间" min-width="160" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="row.task_run_id" size="small" link type="primary" @click="$router.push(`/task-runs/${row.task_run_id}`)">看板</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!data.recent_alerts?.length && !loading" description="暂无告警" :image-size="60" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import LevelBadge from '../components/LevelBadge.vue'
import { getOverview } from '../api/stats'

const data = ref({})
const loading = ref(false)

const levelEntries = computed(() => {
  const dist = data.value.level_dist || {}
  const order = ['crit', 'warn', 'ok', 'unknown']
  const keys = Object.keys(dist).sort((a, b) => order.indexOf(a) - order.indexOf(b))
  return keys.map((k) => [k, dist[k]])
})

function levelTagType(lvl) {
  if (lvl === 'crit') return 'danger'
  if (lvl === 'warn') return 'warning'
  if (lvl === 'ok') return 'success'
  return 'info'
}
function runStatusType(status) {
  if (status === 'RUNNING') return 'warning'
  if (status === 'DONE') return 'success'
  if (status === 'FAILED') return 'danger'
  return 'info'
}
function summaryType(type) {
  if (type === 'success' || type === 'ok') return 'success'
  if (type === 'warn') return 'warning'
  if (type === 'crit' || type === 'error') return 'danger'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    data.value = await getOverview()
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.stat-card {
  cursor: pointer;
  text-align: center;
}
.stat-num {
  font-size: 30px;
  font-weight: 700;
  color: #409eff;
}
.stat-label {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
}
.section-card {
  margin-bottom: 16px;
}
.section-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}
.level-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.level-tag {
  min-width: 96px;
  text-align: center;
}
.tag {
  margin-right: 4px;
}
</style>
