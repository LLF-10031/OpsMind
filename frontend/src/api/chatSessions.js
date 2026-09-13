import request from './request'

export const listSessions = () => request.get('/chat/sessions')

export const createSession = (payload) => request.post('/chat/sessions', payload ?? {})

export const getSession = (id) => request.get(`/chat/sessions/${id}`)

export const updateSession = (id, payload) => request.put(`/chat/sessions/${id}`, payload)

export const deleteSession = (id) => request.delete(`/chat/sessions/${id}`)

export const listMessages = (id, params) => request.get(`/chat/sessions/${id}/messages`, { params })

export const saveMemory = (id, payload) => request.post(`/chat/sessions/${id}/save-memory`, payload)
