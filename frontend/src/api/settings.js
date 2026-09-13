import request from './request'

export const getSettings = () => request.get('/settings')

export const updateSettings = (payload) => request.put('/settings', payload)
