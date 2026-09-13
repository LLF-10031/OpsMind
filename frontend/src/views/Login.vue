<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="login-title">OpsMind 巡检平台</div>
      <div class="login-sub">输入管理密码登录（单管理员账号）</div>
      <el-form @submit.prevent>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="管理密码"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="loading" @click="handleLogin">
          登 录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const password = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!password.value) return
  loading.value = true
  try {
    const data = await login(password.value)
    auth.setToken(data.token)
    router.replace(route.query.redirect || '/dashboard')
  } catch {
    // 拦截器已提示错误
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #2d3f53 100%);
}
.login-card {
  width: 380px;
  padding: 12px 8px;
}
.login-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  color: #1f2d3d;
}
.login-sub {
  text-align: center;
  color: #909399;
  font-size: 13px;
  margin: 6px 0 18px;
}
.login-btn {
  width: 100%;
}
</style>
