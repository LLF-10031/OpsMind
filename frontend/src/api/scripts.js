import request from './request'

export const listScripts = (params) => request.get('/scripts', { params })

export const createScript = (payload) => request.post('/scripts', payload)

export const getScript = (id) => request.get(`/scripts/${id}`)

export const updateScript = (id, payload) => request.put(`/scripts/${id}`, payload)

export const deleteScript = (id) => request.delete(`/scripts/${id}`)

export const runScript = (id, hostId) => request.post(`/scripts/${id}/run`, null, { params: { host_id: hostId } })

export const previewScriptLlm = (id, payload) => request.post(`/scripts/${id}/preview-llm`, payload)

export const listTrackingMetrics = (id) => request.get(`/scripts/${id}/tracking-metrics`)

export const createTrackingMetric = (id, payload) => request.post(`/scripts/${id}/tracking-metrics`, payload)

export const toggleTrackingMetric = (tmId) => request.put(`/tracking-metrics/${tmId}/toggle`)

export const deleteTrackingMetric = (tmId) => request.delete(`/tracking-metrics/${tmId}`)

export const previewTrackingMetric = (tmId, payload) => request.post(`/tracking-metrics/${tmId}/preview`, payload)

export const getScriptTrend = (id, params) => request.get(`/scripts/${id}/trend`, { params })

export const generateTrendSummary = (id, payload) => request.post(`/scripts/${id}/trend-summary`, payload)
