import { defineStore } from 'pinia'

const TOKEN_KEY = 'opsmind_token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || ''
  }),
  getters: {
    isAuthed: (s) => !!s.token
  },
  actions: {
    setToken(token) {
      this.token = token
      localStorage.setItem(TOKEN_KEY, token)
    },
    logout() {
      this.token = ''
      localStorage.removeItem(TOKEN_KEY)
    }
  }
})
