import request from './request'

export const getRun = (id) => request.get(`/runs/${id}`)

export const getRunReport = (id) => request.get(`/runs/${id}/report`)

export const getRunOutput = (id) => request.get(`/runs/${id}/output`)

export const reanalyzeRun = (id) => request.post(`/runs/${id}/reanalyze`, {}, { timeout: 120000 })

export const listRuns = (params) => request.get('/runs', { params })
