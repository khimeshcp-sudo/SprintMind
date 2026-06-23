import { useEffect, useState } from 'react'
import { Plus, Loader2 } from 'lucide-react'
import { api } from '../api/client'

export default function AdminSubscriptions() {
  const [subs, setSubs] = useState([])
  const [users, setUsers] = useState([])
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ user_id: '', plan_id: '', status: 'active' })

  const load = async () => {
    setLoading(true)
    const [s, u, p] = await Promise.all([api.listSubscriptions(), api.listUsers(), api.listPlans()])
    setSubs(s)
    setUsers(u)
    setPlans(p)
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const handleAssign = async (e) => {
    e.preventDefault()
    await api.assignSubscription({
      user_id: Number(form.user_id),
      plan_id: Number(form.plan_id),
      status: form.status,
    })
    setShowForm(false)
    load()
  }

  const statusColor = (s) => ({
    active: 'bg-green-500/20 text-green-300',
    trial: 'bg-blue-500/20 text-blue-300',
    expired: 'bg-red-500/20 text-red-300',
    cancelled: 'bg-gray-500/20 text-gray-300',
  }[s] || 'bg-gray-500/20 text-gray-300')

  const userName = (id) => users.find((u) => u.id === id)?.email || `User #${id}`

  return (
    <div>
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Subscriptions</h1>
          <p className="mt-1 text-gray-400">Assign and manage user subscriptions</p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm(true)}>
          <Plus className="h-4 w-4" /> Assign Plan
        </button>
      </div>

      {showForm && (
        <div className="card mb-6">
          <h2 className="mb-4 text-lg font-semibold">Assign Subscription</h2>
          <form onSubmit={handleAssign} className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">User</label>
              <select className="input-field" value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })} required>
                <option value="">Select user</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.email})</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Plan</label>
              <select className="input-field" value={form.plan_id} onChange={(e) => setForm({ ...form, plan_id: e.target.value })} required>
                <option value="">Select plan</option>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Status</label>
              <select className="input-field" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                <option value="active">Active</option>
                <option value="trial">Trial</option>
                <option value="expired">Expired</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
            <div className="sm:col-span-3 flex gap-3">
              <button type="submit" className="btn-primary">Assign</button>
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
        ) : subs.length === 0 ? (
          <p className="py-16 text-center text-gray-500">No subscriptions yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-surface-600 text-gray-500">
                <th className="pb-3 pr-4">User</th>
                <th className="pb-3 pr-4">Plan</th>
                <th className="pb-3 pr-4">Status</th>
                <th className="pb-3 pr-4">Starts</th>
                <th className="pb-3">Expires</th>
              </tr>
            </thead>
            <tbody>
              {subs.map((s) => (
                <tr key={s.id} className="border-b border-surface-600/50 hover:bg-surface-700/30">
                  <td className="py-3 pr-4 font-medium">{userName(s.user_id)}</td>
                  <td className="py-3 pr-4 text-brand-300">{s.plan?.name || `Plan #${s.plan_id}`}</td>
                  <td className="py-3 pr-4"><span className={`badge ${statusColor(s.status)}`}>{s.status}</span></td>
                  <td className="py-3 pr-4 text-gray-500">{new Date(s.starts_at).toLocaleDateString()}</td>
                  <td className="py-3 text-gray-500">{s.expires_at ? new Date(s.expires_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
