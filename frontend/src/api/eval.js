import request from './request'

export const listEvalCases = (params) => request.get('/eval/cases', { params })

export const createEvalCase = (payload) => request.post('/eval/cases', payload)

export const deleteEvalCase = (id) => request.delete(`/eval/cases/${id}`)

export const runEval = (payload) => request.post('/eval/run', payload)

export const listEvalResults = (params) => request.get('/eval/results', { params })

export const getEvalResult = (id) => request.get(`/eval/results/${id}`)
