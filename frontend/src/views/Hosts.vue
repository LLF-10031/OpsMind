<template>
  <div>
    <div class="page-toolbar">
      <div class="page-hint">管理可控目标主机：MCP 端点连接、连通性探测</div>
      <el-button type="primary" @click="openCreate">新增主机</el-button>
    </div>

    <el-table :data="hosts" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="名称" min-width="140">
        <template #default="{ row }">
          <el-link type="primary" @click="showDetail(row)">{{ row.name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="mcp_endpoint" label="MCP 端点" min-width="240" />
      <el-table-column label="连通状态" width="110">
        <template #default="{ row }">
          <el-tag :type="pingOk(row) ? 'success' : 'info'" size="small">
            {{ row.last_ping_at ? '可达' : '未测' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_ping_at" label="最近探测" width="170" />
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="handlePing(row)">探测</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="detailVisible" :title="detail?.name || '主机详情'" size="420px">
      <template v-if="detail">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">{{ detail.id }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="MCP 端点">{{ detail.mcp_endpoint }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ detail.description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最近探测">{{ detail.last_ping_at || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-sub">绑定任务</div>
        <el-table :data="detailTasks" v-loading="taskLoading" size="small">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="任务名" min-width="120" />
        </el-table>
      </template>
    </el-drawer>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑主机' : '新增主机'" width="520px">
      <el-form label-width="96px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：prod-web-01" />
        </el-form-item>
        <el-form-item label="MCP 端点" required>
          <el-input v-model="form.mcp_endpoint" placeholder="如：mcp://host:port" />
        </el-form-item>
        <el-form-item label="认证密钥">
          <el-input v-model="form.auth_key" type="password" show-password placeholder="可选" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listHosts, createHost, updateHost, deleteHost, pingHost, listHostTasks } from '../api/hosts'

const hosts = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({ name: '', mcp_endpoint: '', auth_key: '', description: '' })

const detailVisible = ref(false)
const detail = ref(null)
const detailTasks = ref([])
const taskLoading = ref(false)

const pingOk = (row) => !!row.last_ping_at

async function load() {
  loading.value = true
  try {
    hosts.value = await listHosts()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', mcp_endpoint: '', auth_key: '', description: '' })
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, {
    name: row.name,
    mcp_endpoint: row.mcp_endpoint,
    auth_key: '',
    description: row.description || ''
  })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.name || !form.mcp_endpoint) {
    ElMessage.warning('名称与 MCP 端点必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const payload = { name: form.name, mcp_endpoint: form.mcp_endpoint, description: form.description }
      if (form.auth_key) payload.auth_key = form.auth_key
      await updateHost(editing.value.id, payload)
    } else {
      await createHost({ ...form })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function handlePing(row) {
  try {
    const result = await pingHost(row.id)
    ElMessage.success(result.status || '连通')
    load()
  } catch {
    // 拦截器已提示
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`删除主机「${row.name}」？`, '确认', { type: 'warning' })
  await deleteHost(row.id)
  ElMessage.success('已删除')
  load()
}

async function showDetail(row) {
  detail.value = row
  detailVisible.value = true
  taskLoading.value = true
  try {
    detailTasks.value = await listHostTasks(row.id)
  } finally {
    taskLoading.value = false
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
.drawer-sub {
  margin: 16px 0 8px;
  font-weight: 600;
}
</style>
