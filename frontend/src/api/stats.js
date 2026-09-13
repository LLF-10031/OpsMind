import request from './request'

export const getOverview = () => request.get('/stats/overview')
