import request from './request'

export const listHosts = () => request.get('/hosts')

export const createHost = (payload) => request.post('/hosts', payload)

export const getHost = (id) => request.get(`/hosts/${id}`)

export const updateHost = (id, payload) => request.put(`/hosts/${id}`, payload)

export const deleteHost = (id) => request.delete(`/hosts/${id}`)

export const pingHost = (id) => request.post(`/hosts/${id}/ping`)

export const listHostTasks = (id) => request.get(`/hosts/${id}/tasks`)
