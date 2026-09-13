import request from './request'

export const listTemplates = (params) => request.get('/templates', { params })

export const createTemplate = (payload) => request.post('/templates', payload)

export const getTemplate = (id) => request.get(`/templates/${id}`)

export const updateTemplate = (id, payload) => request.put(`/templates/${id}`, payload)

export const deleteTemplate = (id) => request.delete(`/templates/${id}`)

export const applyTemplate = (id, hostId) => request.post(`/templates/${id}/apply`, { host_id: hostId })
