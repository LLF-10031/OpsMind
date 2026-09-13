import request from './request'

export const login = (password) => request.post('/auth/login', { password })

export const verify = () => request.get('/auth/verify')

export const logout = () => request.post('/auth/logout')
