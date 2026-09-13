<template>
  <router-view />
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { verify } from './api/auth'

const auth = useAuthStore()
const router = useRouter()
auth.setToken(auth.token)

onMounted(async () => {
  if (!auth.isAuthed) return
  try {
    await verify()
  } catch {
    // token 失效：清 store + localStorage（拦截器只清 localStorage，会导致 guard 弹跳）
    auth.logout()
    router.replace('/login')
  }
})
</script>
