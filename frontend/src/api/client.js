// Use relative /api paths — proxied by nginx (Docker) or Vite dev server.
// Do NOT set VITE_API_URL to an absolute URL unless you know what you're doing.
const API_BASE = import.meta.env.VITE_API_URL || ''

function getToken() {
  return localStorage.getItem('token')
}

async function parseResponse(res) {
  const text = await res.text()
  const contentType = res.headers.get('content-type') || ''

  if (contentType.includes('application/json') || text.trimStart().startsWith('{')) {
    try {
      return JSON.parse(text)
    } catch {
      return {}
    }
  }

  if (text.trimStart().startsWith('<')) {
    throw new Error(
      'Backend unavailable (received HTML instead of JSON). ' +
        'Run: docker compose up -d   or start API on port 8000.'
    )
  }

  return text ? { detail: text } : {}
}

async function request(path, options = {}) {
  const headers = { ...options.headers }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const isForm = options.body instanceof FormData
  if (!isForm && options.body && typeof options.body === 'object') {
    headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(options.body)
  }

  let res
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch {
    throw new Error('Cannot reach API. Start backend: docker compose up -d')
  }

  if (res.status === 204) return null

  const data = await parseResponse(res)
  if (!res.ok) {
    const detail = data.detail
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg || d).join(', ')
      : detail || data.message || `Request failed (${res.status})`
    throw new Error(message)
  }
  return data
}

export const api = {
  login: async (email, password) => {
    const form = new URLSearchParams()
    form.append('username', email)
    form.append('password', password)
    let res
    try {
      res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form,
      })
    } catch {
      throw new Error('Cannot reach API. Start backend: docker compose up -d')
    }
    const data = await parseResponse(res)
    if (!res.ok) throw new Error(data.detail || 'Login failed')
    return data
  },

  register: (body) => request('/api/auth/register', { method: 'POST', body }),
  me: () => request('/api/auth/me'),
  mySubscription: () => request('/api/auth/me/subscription'),

  billingConfig: () => request('/api/billing/config'),
  billingStatus: () => request('/api/billing/status'),
  verifyCheckoutSession: (sessionId) =>
    request('/api/billing/verify-session', { method: 'POST', body: { session_id: sessionId } }),
  syncBilling: () => request('/api/billing/sync', { method: 'POST' }),
  checkout: (planId) => request('/api/billing/checkout', { method: 'POST', body: { plan_id: planId } }),
  billingPortal: () => request('/api/billing/portal', { method: 'POST' }),

  dashboard: () => request('/api/tasks/dashboard'),
  listTasks: () => request('/api/tasks'),
  getTask: (id) => request(`/api/tasks/${id}`),
  createTask: (body) => request('/api/tasks', { method: 'POST', body }),
  uploadTask: (formData) => request('/api/tasks/upload', { method: 'POST', body: formData }),
  updateTask: (id, body) => request(`/api/tasks/${id}`, { method: 'PATCH', body }),
  updateTaskUpload: (id, formData) => request(`/api/tasks/${id}/upload`, { method: 'PATCH', body: formData }),
  deleteTask: (id) => request(`/api/tasks/${id}`, { method: 'DELETE' }),

  workflowSteps: () => request('/api/tasks/workflow/steps'),
  startWorkflow: (taskId) => request(`/api/tasks/${taskId}/workflow/start`, { method: 'POST' }),
  stopWorkflow: (taskId) => request(`/api/tasks/${taskId}/workflow/stop`, { method: 'POST' }),
  restartWorkflow: (taskId) => request(`/api/tasks/${taskId}/workflow/restart`, { method: 'POST' }),
  getWorkflow: (taskId) => request(`/api/tasks/${taskId}/workflow`),
  resumeWorkflow: (taskId, body) =>
    request(`/api/tasks/${taskId}/workflow/resume`, { method: 'POST', body }),

  listUsers: () => request('/api/users'),
  createUser: (body) => request('/api/users', { method: 'POST', body }),
  updateUser: (id, body) => request(`/api/users/${id}`, { method: 'PATCH', body }),
  deleteUser: (id) => request(`/api/users/${id}`, { method: 'DELETE' }),

  listPlans: () => request('/api/plans'),
  createPlan: (body) => request('/api/plans', { method: 'POST', body }),
  updatePlan: (id, body) => request(`/api/plans/${id}`, { method: 'PATCH', body }),
  deletePlan: (id) => request(`/api/plans/${id}`, { method: 'DELETE' }),

  listSubscriptions: () => request('/api/subscriptions'),
  assignSubscription: (body) => request('/api/subscriptions', { method: 'POST', body }),
}
