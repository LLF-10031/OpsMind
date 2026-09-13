import request from './request'

export const listMemory = (params) => request.get('/memory', { params })

export const saveMemory = (payload) => request.post('/memory', payload)

export const editMemory = (type, id, payload) => request.put(`/memory/${type}/${id}`, payload)

export const deleteMemory = (type, id) => request.delete(`/memory/${type}/${id}`)

export const queryMemory = (payload) => request.post('/memory/query', payload)
