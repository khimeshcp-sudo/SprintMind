import { useEffect, useState } from 'react'
import { Plus, Upload, Trash2, Pencil, X, Loader2, Paperclip, Bot } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    title: '',
    description: '',
    jira_key: '',
    status: 'pending',
    file: null,
    existingFileName: '',
  })

  const load = () => {
    setLoading(true)
    api.listTasks().then(setTasks).catch(console.error).finally(() => setLoading(false))
  }

  useEffect(load, [])

  const resetForm = () => {
    setForm({
      title: '',
      description: '',
      jira_key: '',
      status: 'pending',
      file: null,
      existingFileName: '',
    })
    setEditId(null)
    setShowForm(false)
    setError('')
  }

  const buildFormData = () => {
    const fd = new FormData()
    fd.append('title', form.title)
    fd.append('description', form.description)
    if (form.jira_key) fd.append('jira_key', form.jira_key)
    if (editId) fd.append('status', form.status)
    if (form.file) fd.append('file', form.file)
    return fd
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    try {
      if (editId) {
        if (form.file) {
          await api.updateTaskUpload(editId, buildFormData())
        } else {
          await api.updateTask(editId, {
            title: form.title,
            description: form.description,
            jira_key: form.jira_key || null,
            status: form.status,
          })
        }
      } else if (form.file) {
        await api.uploadTask(buildFormData())
      } else {
        await api.createTask({
          title: form.title,
          description: form.description,
          jira_key: form.jira_key || null,
        })
      }
      resetForm()
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this task?')) return
    await api.deleteTask(id)
    load()
  }

  const startEdit = (task) => {
    setEditId(task.id)
    setForm({
      title: task.title,
      description: task.description,
      jira_key: task.jira_key || '',
      status: task.status,
      file: null,
      existingFileName: task.file_name || '',
    })
    setShowForm(true)
  }

  const statusBadge = (status) => {
    const map = {
      pending: 'bg-yellow-500/20 text-yellow-300',
      in_progress: 'bg-blue-500/20 text-blue-300',
      completed: 'bg-green-500/20 text-green-300',
      failed: 'bg-red-500/20 text-red-300',
    }
    return <span className={`badge ${map[status]}`}>{status.replace('_', ' ')}</span>
  }

  return (
    <div>
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">My Tasks</h1>
          <p className="mt-1 text-gray-400">Upload and manage your Magento tasks</p>
        </div>
        <button className="btn-primary" onClick={() => { resetForm(); setShowForm(true) }}>
          <Plus className="h-4 w-4" /> New Task
        </button>
      </div>

      {showForm && (
        <div className="card mb-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">{editId ? 'Edit Task' : 'Create Task'}</h2>
            <button onClick={resetForm} className="text-gray-500 hover:text-gray-300"><X className="h-5 w-5" /></button>
          </div>
          {error && <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>}
          <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="mb-1.5 block text-sm font-medium text-gray-300">Title *</label>
              <input className="input-field" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1.5 block text-sm font-medium text-gray-300">Description</label>
              <textarea className="input-field min-h-[100px] resize-y" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-300">Jira Key</label>
              <input className="input-field" placeholder="MAG-123" value={form.jira_key} onChange={(e) => setForm({ ...form, jira_key: e.target.value })} />
            </div>
            {editId && (
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-300">Status</label>
                <select className="input-field" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="pending">Pending</option>
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                  <option value="failed">Failed</option>
                </select>
              </div>
            )}
            <div className={editId ? 'sm:col-span-2' : ''}>
              <label className="mb-1.5 block text-sm font-medium text-gray-300">
                {editId ? 'Replace / Attach File' : 'Attach File'}
              </label>
              {form.existingFileName && !form.file && (
                <p className="mb-2 flex items-center gap-2 text-xs text-gray-400">
                  <Paperclip className="h-3.5 w-3.5" />
                  Current file: <span className="text-brand-300">{form.existingFileName}</span>
                </p>
              )}
              <input
                type="file"
                className="input-field file:mr-4 file:rounded-lg file:border-0 file:bg-brand-600 file:px-4 file:py-2 file:text-sm file:text-white"
                onChange={(e) => setForm({ ...form, file: e.target.files?.[0] || null })}
              />
              {form.file && (
                <p className="mt-1.5 text-xs text-green-400">Selected: {form.file.name}</p>
              )}
            </div>
            <div className="sm:col-span-2 flex gap-3">
              <button type="submit" className="btn-primary">
                <Upload className="h-4 w-4" /> {editId ? 'Save Changes' : 'Save Task'}
              </button>
              <button type="button" className="btn-secondary" onClick={resetForm}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
        ) : tasks.length === 0 ? (
          <p className="py-16 text-center text-gray-500">No tasks yet. Click &quot;New Task&quot; to get started.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-600 text-gray-500">
                  <th className="pb-3 pr-4 font-medium">Title</th>
                  <th className="pb-3 pr-4 font-medium">Jira</th>
                  <th className="pb-3 pr-4 font-medium">File</th>
                  <th className="pb-3 pr-4 font-medium">Status</th>
                  <th className="pb-3 pr-4 font-medium">Created</th>
                  <th className="pb-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id} className="border-b border-surface-600/50 hover:bg-surface-700/30">
                    <td className="py-3 pr-4">
                      <p className="font-medium">{t.title}</p>
                      {t.description && <p className="mt-0.5 text-xs text-gray-500 line-clamp-1">{t.description}</p>}
                    </td>
                    <td className="py-3 pr-4 text-gray-400">{t.jira_key || '—'}</td>
                    <td className="py-3 pr-4 text-gray-400">{t.file_name || '—'}</td>
                    <td className="py-3 pr-4">{statusBadge(t.status)}</td>
                    <td className="py-3 pr-4 text-gray-500">{new Date(t.created_at).toLocaleDateString()}</td>
                    <td className="py-3">
                      <div className="flex gap-2">
                        <Link
                          to={`/tasks/${t.id}`}
                          className="rounded-lg p-2 text-gray-400 hover:bg-surface-700 hover:text-brand-300"
                          title="AI Flow"
                        >
                          <Bot className="h-4 w-4" />
                        </Link>
                        <button onClick={() => startEdit(t)} className="rounded-lg p-2 text-gray-400 hover:bg-surface-700 hover:text-brand-300"><Pencil className="h-4 w-4" /></button>
                        <button onClick={() => handleDelete(t.id)} className="rounded-lg p-2 text-gray-400 hover:bg-surface-700 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
