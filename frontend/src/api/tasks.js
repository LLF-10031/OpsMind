import request from './request'

export const listTasks = (hostId) => request.get(`/hosts/${hostId}/tasks`)

export const createTask = (payload) => request.post('/tasks', payload)

export const getTask = (id) => request.get(`/tasks/${id}`)

export const updateTask = (id, payload) => request.put(`/tasks/${id}`, payload)

export const toggleTask = (id, isEnabled = true) => request.put(`/tasks/${id}/toggle`, { is_enabled: isEnabled })

export const runTask = (id) => request.post(`/tasks/${id}/run`)

export const deleteTask = (id) => request.delete(`/tasks/${id}`)

export const listTaskRuns = (id) => request.get(`/tasks/${id}/runs`)
