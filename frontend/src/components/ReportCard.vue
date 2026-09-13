<template>
  <div class="report-card">
    <template v-if="!report">
      <el-empty description="暂无报告" :image-size="60" />
    </template>
    <template v-else>
      <div class="rc-head">
        <span class="rc-label">报告</span>
        <LevelBadge :level="reportLevel" />
        <el-tag size="small" type="info">{{ reportTypeText }}</el-tag>
        <template v-if="run">
          <span class="rc-meta">exit={{ run.exit_code }}</span>
          <span class="rc-meta">{{ (run.duration_ms / 1000).toFixed(2) }}s</span>
        </template>
      </div>

      <div v-if="report.banner" class="rc-banner">{{ report.banner }}</div>

      <div v-if="isSuccessOk" class="rc-ok">
        <div class="rc-ok-title">正常</div>
        <div class="rc-ok-sub">脚本执行成功，状态符合预期，无异常需要关注。</div>
      </div>

      <div v-else-if="isSuccessWarn" class="rc-warn">
        <div class="rc-title">存在异常，请关注</div>
        <div class="rc-marg">{{ aiText }}</div>
      </div>

      <div v-else-if="isSuccessCrit" class="rc-crit">
        <div class="rc-title">深度诊断中</div>
        <div class="rc-marg rc-dim">该报告命中严重级别，正在执行异常联动诊断，结论将回填至下方批次诊断块。</div>
      </div>

      <div v-else-if="isSuccessUnknown" class="rc-unknown">
        <div class="rc-dim">未配置 AI 模型，仅数据不分析（灰标存疑）</div>
        <div v-if="report.ai_content" class="rc-marg">{{ report.ai_content }}</div>
      </div>

      <div v-else-if="reportType === 'error'" class="rc-error">
        <div class="rc-title">执行失败</div>
        <div class="rc-marg">{{ aiText || '脚本执行失败，无可用诊断内容。' }}</div>
      </div>

      <div v-else-if="reportType === 'timeout'" class="rc-timeout">
        <div class="rc-title">执行超时</div>
        <div class="rc-marg">请检查网络/目标服务配置</div>
      </div>

      <div v-else-if="reportType === 'host_unreachable'" class="rc-timeout">
        <div class="rc-title">主机不可达</div>
        <div class="rc-marg">目标机不可达，请检查网络与执行服务状态</div>
      </div>

      <div v-else class="rc-timeout">
        <div class="rc-title">暂无输出</div>
        <div class="rc-marg">脚本未产生任何输出。</div>
      </div>

      <div v-if="report.degradation_notes" class="rc-notes">
        降级说明：{{ report.degradation_notes }}
      </div>
      <div v-if="annotations.length" class="rc-notes-list">
        <div v-for="a in annotations" :key="a.rule" class="rc-note">
          [{{ a.rule }}] {{ a.message }}
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import LevelBadge from './LevelBadge.vue'

const props = defineProps({
  report: { type: Object, default: null },
  run: { type: Object, default: null }
})

const reportType = computed(() => props.report?.report_type || '')
const level = computed(() => props.report?.meta?.level || props.run?.level || 'unknown')

const REPORT_TYPE_TEXT = {
  success: '成功',
  error: '错误',
  timeout: '超时',
  empty: '空输出',
  host_unreachable: '不可达'
}
const reportTypeText = computed(() => REPORT_TYPE_TEXT[reportType.value] || reportType.value)

const isSuccessOk = computed(() => reportType.value === 'success' && level.value === 'ok')
const isSuccessWarn = computed(() => reportType.value === 'success' && level.value === 'warn')
const isSuccessCrit = computed(() => reportType.value === 'success' && level.value === 'crit')
const isSuccessUnknown = computed(() => reportType.value === 'success' && level.value !== 'ok' && level.value !== 'warn' && level.value !== 'crit')

const aiText = computed(() => props.report?.ai_content || '')
const annotations = computed(() => Object.prototype.toString.call(props.report?.annotations) === '[object Array]' ? props.report.annotations : [])
</script>

<style scoped>
.report-card {
  font-size: 14px;
  line-height: 1.7;
}
.rc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.rc-label {
  font-weight: 600;
}
.rc-meta {
  color: #909399;
  font-size: 12px;
}
.rc-banner {
  background: #fef0f0;
  color: #f56c6c;
  border: 1px solid #fde2e2;
  border-radius: 4px;
  padding: 8px 12px;
  margin-bottom: 12px;
}
.rc-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 6px;
}
.rc-marg {
  margin-bottom: 6px;
}
.rc-dim {
  color: #909399;
}
.rc-ok-title {
  font-size: 24px;
  font-weight: 700;
  color: #67c23a;
}
.rc-ok-sub {
  color: #67c23a;
  opacity: 0.9;
}
.rc-notes {
  margin-top: 12px;
  color: #e6a23c;
  font-size: 13px;
}
.rc-notes-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rc-note {
  font-size: 12px;
  color: #909399;
  background: #f4f4f5;
  border-radius: 3px;
  padding: 4px 8px;
}
</style>
