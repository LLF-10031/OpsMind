<template>
  <el-tag :type="type" size="small" effect="light">{{ text }}</el-tag>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  level: { type: String, default: 'unknown' }
})

const MAP = {
  ok: { text: '正常', type: 'success' },
  warn: { text: '警告', type: 'warning' },
  crit: { text: '严重', type: 'danger' },
  unknown: { text: '未知', type: 'info' }
}

const type = computed(() => MAP[props.level]?.type || 'info')
const text = computed(() => MAP[props.level]?.text || props.level || '未知')
</script>
