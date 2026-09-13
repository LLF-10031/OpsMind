import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

import Layout from '../Layout.vue'
import Login from '../views/Login.vue'
import Dashboard from '../views/Dashboard.vue'
import Hosts from '../views/Hosts.vue'
import Scripts from '../views/Scripts.vue'
import Templates from '../views/Templates.vue'
import Documents from '../views/Documents.vue'
import Tasks from '../views/Tasks.vue'
import TaskRunBoard from '../views/TaskRunBoard.vue'
import Assistant from '../views/Assistant.vue'
import Eval from '../views/Eval.vue'
import Reports from '../views/Reports.vue'
import Memory from '../views/Memory.vue'
import Settings from '../views/Settings.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: Login, meta: { public: true } },
    {
      path: '/',
      component: Layout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'dashboard', component: Dashboard },
        { path: 'hosts', name: 'hosts', component: Hosts },
        { path: 'scripts', name: 'scripts', component: Scripts },
        { path: 'templates', name: 'templates', component: Templates },
        { path: 'documents', name: 'documents', component: Documents },
        { path: 'tasks', name: 'tasks', component: Tasks },
        { path: 'task-runs/:id', name: 'task-run-board', component: TaskRunBoard, props: true },
        { path: 'assistant', name: 'assistant', component: Assistant },
        { path: 'eval', name: 'eval', component: Eval },
        { path: 'reports', name: 'reports', component: Reports },
        { path: 'memory', name: 'memory', component: Memory },
        { path: 'settings', name: 'settings', component: Settings }
      ]
    }
  ]
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthed) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && auth.isAuthed) {
    return '/dashboard'
  }
  return true
})

export default router
