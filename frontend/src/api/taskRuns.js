import request from './request'
import { baseURL } from './base'

export const getTaskRun = (id) => request.get(`/task-runs/${id}`)

export const listRunsOfTaskRun = (id) => request.get(`/task-runs/${id}/runs`)

export const cancelTaskRun = (id) => request.post(`/task-runs/${id}/cancel`)

export const streamUrl = (id) => `${baseURL}/task-runs/${id}/stream`
