import request from './request'

export const listDocuments = () => request.get('/documents')

export const uploadDocument = (file) => {
  const form = new FormData()
  form.append('file', file)
  return request.post('/documents', form)
}

export const getDocument = (id) => request.get(`/documents/${id}`)

export const getDocumentContent = (id) => request.get(`/documents/${id}/content`)

export const previewDocument = (id) => request.post(`/documents/${id}/preview`, null, { params: { limit: 50 } })

export const deleteDocument = (id) => request.delete(`/documents/${id}`)

export const searchDocuments = (query, options = {}) =>
  request.post('/documents/search', { query, ...options })
