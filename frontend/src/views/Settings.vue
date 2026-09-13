<template>
  <div class="settings-page">
    <el-card shadow="never">
      <template #header>
        <div class="settings-head">
          <span>系统设置</span>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </div>
      </template>

      <!-- 对话/分析模型 -->
      <el-divider content-position="left">对话 / 分析模型</el-divider>
      <el-form label-width="180px" style="max-width: 680px">
        <el-form-item label="模型">
          <el-input v-model="form.llm_model" placeholder="如 qwen-max" />
        </el-form-item>
        <el-form-item label="API Base URL">
          <el-input v-model="form.llm_base_url" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.llm_api_key" type="password" show-password
            :placeholder="maskOf('llm_api_key') || '请输入 API Key'" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-input-number v-model="form.llm_temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
      </el-form>

      <!-- 文档处理 / 轻任务模型 -->
      <el-divider content-position="left">文档处理 / 轻任务模型</el-divider>
      <el-form label-width="180px" style="max-width: 680px">
        <el-form-item label="轻任务模型">
          <el-input v-model="form.light_model" placeholder="压缩/摘要/记忆提炼，如 qwen-turbo" />
        </el-form-item>
        <el-form-item label="文档处理模型">
          <el-input v-model="form.docproc_model" placeholder="多模态/图片解析，如 qwen-vl-max（可空）" />
        </el-form-item>
        <el-form-item label="API Base URL">
          <el-input v-model="form.docproc_base_url" placeholder="留空则复用对话 Base URL" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.docproc_api_key" type="password" show-password
            :placeholder="maskOf('docproc_api_key') || '留空则复用对话 API Key'" />
        </el-form-item>
        <el-form-item>
          <el-button size="small" @click="reuseDefault('docproc')">复用对话配置</el-button>
        </el-form-item>
      </el-form>

      <!-- 向量 embedding 模型 -->
      <el-divider content-position="left">向量 / Embedding 模型</el-divider>
      <el-form label-width="180px" style="max-width: 680px">
        <el-form-item label="Embedding 模型">
          <el-input v-model="form.embedding_model" placeholder="如 text-embedding-v3" />
        </el-form-item>
        <el-form-item label="API Base URL">
          <el-input v-model="form.embedding_base_url" placeholder="留空则复用对话 Base URL" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.embedding_api_key" type="password" show-password
            :placeholder="maskOf('embedding_api_key') || '留空则复用对话 API Key'" />
        </el-form-item>
        <el-form-item>
          <el-button size="small" @click="reuseDefault('embedding')">复用对话配置</el-button>
        </el-form-item>
      </el-form>

      <!-- 其他设置 -->
      <el-divider content-position="left">其他设置</el-divider>
      <el-form label-width="180px" style="max-width: 680px">
        <el-form-item v-if="form.llm_provider !== undefined" label="LLM 提供商">
          <el-input v-model="form.llm_provider" />
        </el-form-item>
        <el-form-item v-if="form.default_analysis_model !== undefined" label="默认分析模型">
          <el-input v-model="form.default_analysis_model" />
        </el-form-item>
        <el-form-item v-if="form.injection_detection_enabled !== undefined" label="注入检测">
          <el-switch v-model="form.injection_detection_enabled" />
        </el-form-item>
        <el-form-item v-if="form.default_document_ids !== undefined" label="默认知识库文档">
          <el-select v-model="form.default_document_ids" multiple filterable placeholder="文档 ID（可多个）"
            style="width: 100%">
            <el-option v-for="d in docOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.pipeline_config !== undefined" label="校验流水线配置">
          <el-input v-model="pipelineText" type="textarea" :rows="4" placeholder='{"enabled": true}' />
        </el-form-item>
      </el-form>
      <div class="settings-tip">
        说明：API Key 已配置时显示掩码，重新输入才会覆盖；文档处理 / 向量留空则自动复用对话配置。
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSettings, updateSettings } from '../api/settings'
import { listDocuments } from '../api/documents'

const form = ref({})
const pipelineText = ref('')
const saving = ref(false)
const docOptions = ref([])

function maskOf(key) {
  const v = form.value[key]
  return typeof v === 'string' && v.startsWith('******') ? v : ''
}

function normalize(raw) {
  form.value = { ...raw }
  const cfg = raw.pipeline_config
  pipelineText.value = typeof cfg === 'string' ? cfg : JSON.stringify(cfg ?? {}, null, 2)
}

async function load() {
  const data = await getSettings()
  normalize(data)
}

function reuseDefault(which) {
  if (which === 'docproc') {
    form.value.docproc_base_url = form.value.llm_base_url
    form.value.docproc_api_key = ''
  } else if (which === 'embedding') {
    form.value.embedding_base_url = form.value.llm_base_url
    form.value.embedding_api_key = ''
  }
}

async function save() {
  saving.value = true
  try {
    const payload = { ...form.value }
    if (form.value.pipeline_config !== undefined) {
      try {
        payload.pipeline_config = JSON.parse(pipelineText.value || '{}')
      } catch {
        ElMessage.error('校验流水线配置不是合法 JSON')
        return
      }
    }
    await updateSettings(payload)
    ElMessage.success('设置已保存')
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load().catch(() => {})
  listDocuments().then((d) => { docOptions.value = d }).catch(() => {})
})
</script>

<style scoped>
.settings-page {
  max-width: 900px;
}
.settings-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.settings-tip {
  margin-top: 12px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
</style>