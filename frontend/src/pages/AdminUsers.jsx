import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, X, Loader2 } from 'lucide-react'
import { api } from '../api/client'

export default function AdminUsers() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState(null)
  const [form, setForm] = useState({ email: '', full_name: '', password: '', role: 'user', is_active: true })

  const load = () => {
    setLoading(true)
    api.listUsers().then(setUsers).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const reset = () => {
    setForm({ email: '', full_name: '', password: '', role: 'user', is_active: true })
    setEditId(null)
    setShowForm(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const body = { ...form }
    if (editId && !body.password) delete body.password
    if (editId) await api.updateUser(editId, body)
    else await api.createUser(body)
    reset()
    load()
  }

  const startEdit = (u) => {
    setEditId(u.id)
    setForm({ email: u.email, full_name: u.full_name, password: '', role: u.role, is_active: u.is_active })
    setShowForm(true)
  }

  return (
    <div>
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">User Management</h1>
          <p className="mt-1 text-gray-400">CRUD users with role-based access</p>
        </div>
        <button className="btn-primary" onClick={() => { reset(); setShowForm(true) }}>
          <Plus className="h-4 w-4" /> Add User
        </button>
      </div>

      {showForm && (
        <div className="card mb-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">{editId ? 'Edit User' : 'New User'}</h2>
            <button onClick={reset}><X className="h-5 w-5 text-gray-500" /></button>
          </div>
          <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Email</label>
              <input className="input-field" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Full Name</label>
              <input className="input-field" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Password {editId && '(leave blank to keep)'}</label>
              <input className="input-field" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} {...(!editId && { required: true, minLength: 6 })} />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Role</label>
              <select className="input-field" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="flex items-center gap-2 sm:col-span-2">
              <input type="checkbox" id="active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} className="rounded" />
              <label htmlFor="active" className="text-sm text-gray-300">Active</label>
            </div>
            <div className="sm:col-span-2">
              <button type="submit" className="btn-primary">Save User</button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-surface-600 text-gray-500">
                <th className="pb-3 pr-4">Name</th>
                <th className="pb-3 pr-4">Email</th>
                <th className="pb-3 pr-4">Role</th>
                <th className="pb-3 pr-4">Status</th>
                <th className="pb-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-surface-600/50 hover:bg-surface-700/30">
                  <td className="py-3 pr-4 font-medium">{u.full_name}</td>
                  <td className="py-3 pr-4 text-gray-400">{u.email}</td>
                  <td className="py-3 pr-4">
                    <span className={`badge ${u.role === 'admin' ? 'bg-brand-500/20 text-brand-300' : 'bg-surface-600 text-gray-300'}`}>{u.role}</span>
                  </td>
                  <td className="py-3 pr-4">
                    <span className={`badge ${u.is_active ? 'bg-green-500/20 text-green-300' : 'bg-red-500/20 text-red-300'}`}>
                      {u.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="py-3">
                    <div className="flex gap-2">
                      <button onClick={() => startEdit(u)} className="rounded-lg p-2 text-gray-400 hover:text-brand-300"><Pencil className="h-4 w-4" /></button>
                      <button onClick={() => { if (confirm('Delete?')) api.deleteUser(u.id).then(load) }} className="rounded-lg p-2 text-gray-400 hover:text-red-300"><Trash2 className="h-4 w-4" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
