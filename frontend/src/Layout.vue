<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <span class="brand-name">OpsMind</span>
        <span class="brand-sub">巡检平台</span>
      </div>
      <el-menu :default-active="activeMenu" router class="menu">
        <el-menu-item index="/dashboard">概览</el-menu-item>
        <el-menu-item index="/hosts">主机管理</el-menu-item>
        <el-menu-item index="/scripts">脚本库</el-menu-item>
        <el-menu-item index="/templates">模板库</el-menu-item>
        <el-menu-item index="/documents">知识库</el-menu-item>
        <el-menu-item index="/tasks">巡检任务</el-menu-item>
        <el-menu-item index="/eval">评估</el-menu-item>
        <el-menu-item index="/reports">报告</el-menu-item>
        <el-menu-item index="/assistant">AI 助手</el-menu-item>
        <el-menu-item index="/memory">记忆</el-menu-item>
        <el-menu-item index="/settings">系统设置</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">
          <span v-if="breadcrumb">{{ breadcrumb }}</span>
        </div>
        <div class="header-right">
          <el-tag type="info" size="small">admin</el-tag>
          <el-button link type="danger" @click="handleLogout">退出登录</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from './stores/auth'
import { logout as apiLogout } from './api/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const activeMenu = computed(() => {
  if (route.name === 'task-run-board') return '/tasks'
  return route.path
})

const titleMap = {
  '/dashboard': '概览',
  '/hosts': '主机管理',
  '/scripts': '脚本库',
  '/templates': '模板库',
  '/documents': '知识库',
  '/tasks': '巡检任务',
  '/assistant': 'AI 助手',
  '/eval': '评估',
  '/reports': '报告',
  '/memory': '记忆',
  '/settings': '系统设置'
}
const breadcrumb = computed(() => {
  if (route.name === 'task-run-board') return '巡检看板'
  return titleMap[route.path] || ''
})

async function handleLogout() {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  try {
    await apiLogout()
  } catch {
    // 后端登出失败不强求
  }
  auth.logout()
  router.replace('/login')
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #1f2d3d;
}
.brand {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  color: #fff;
}
.brand-name {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
}
.brand-sub {
  font-size: 12px;
  color: #8aa3bd;
}
.menu {
  border-right: none;
  background: transparent;
}
.menu :deep(.el-menu-item) {
  color: #c0ccda;
}
.menu :deep(.el-menu-item:hover),
.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: #28303d;
}
.header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-title {
  font-size: 16px;
  font-weight: 600;
}
.main {
  background: #f5f7fa;
}
</style>
