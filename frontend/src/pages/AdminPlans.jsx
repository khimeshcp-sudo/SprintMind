import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, X, Loader2 } from 'lucide-react'
import { api } from '../api/client'

export default function AdminPlans() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState(null)
  const [form, setForm] = useState({ name: '', description: '', price_monthly: 0, max_tasks: 10, max_users: 1, is_active: true, stripe_price_id: '' })

  const load = () => {
    setLoading(true)
    api.listPlans().then(setPlans).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const reset = () => {
    setForm({ name: '', description: '', price_monthly: 0, max_tasks: 10, max_users: 1, is_active: true, stripe_price_id: '' })
    setEditId(null)
    setShowForm(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const body = {
      ...form,
      price_monthly: Number(form.price_monthly),
      max_tasks: Number(form.max_tasks),
      max_users: Number(form.max_users),
      stripe_price_id: form.stripe_price_id || null,
    }
    if (editId) await api.updatePlan(editId, body)
    else await api.createPlan(body)
    reset()
    load()
  }

  const formatPrice = (cents) => cents === 0 ? 'Free' : `$${(cents / 100).toFixed(2)}/mo`

  return (
    <div>
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Subscription Plans</h1>
          <p className="mt-1 text-gray-400">Manage SaaS pricing tiers</p>
        </div>
        <button className="btn-primary" onClick={() => { reset(); setShowForm(true) }}>
          <Plus className="h-4 w-4" /> Add Plan
        </button>
      </div>

      {showForm && (
        <div className="card mb-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">{editId ? 'Edit Plan' : 'New Plan'}</h2>
            <button onClick={reset}><X className="h-5 w-5 text-gray-500" /></button>
          </div>
          <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Plan Name</label>
              <input className="input-field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Price (cents/month)</label>
              <input className="input-field" type="number" value={form.price_monthly} onChange={(e) => setForm({ ...form, price_monthly: e.target.value })} />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1.5 block text-sm text-gray-300">Description</label>
              <textarea className="input-field" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Max Tasks</label>
              <input className="input-field" type="number" value={form.max_tasks} onChange={(e) => setForm({ ...form, max_tasks: e.target.value })} />
            </div>
            <div>
              <label className="mb-1.5 block text-sm text-gray-300">Max Users</label>
              <input className="input-field" type="number" value={form.max_users} onChange={(e) => setForm({ ...form, max_users: e.target.value })} />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1.5 block text-sm text-gray-300">Stripe Price ID</label>
              <input className="input-field" placeholder="price_xxx (paid plans)" value={form.stripe_price_id || ''} onChange={(e) => setForm({ ...form, stripe_price_id: e.target.value })} />
            </div>
            <div className="sm:col-span-2">
              <button type="submit" className="btn-primary">Save Plan</button>
            </div>
          </form>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {loading ? (
          <div className="col-span-full flex justify-center py-16"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
        ) : plans.map((p) => (
          <div key={p.id} className={`card relative ${!p.is_active ? 'opacity-50' : ''}`}>
            <div className="mb-4">
              <h3 className="text-xl font-bold">{p.name}</h3>
              <p className="mt-1 text-2xl font-bold text-brand-400">{formatPrice(p.price_monthly)}</p>
            </div>
            <p className="mb-4 text-sm text-gray-400">{p.description}</p>
            <ul className="mb-6 space-y-2 text-sm text-gray-300">
              <li>✓ {p.max_tasks} tasks</li>
              <li>✓ {p.max_users} users</li>
              {p.stripe_price_id && <li className="text-xs text-gray-500">Stripe: {p.stripe_price_id}</li>}
            </ul>
            <div className="flex gap-2">
              <button onClick={() => { setEditId(p.id); setForm(p); setShowForm(true) }} className="btn-secondary flex-1 text-xs"><Pencil className="h-3 w-3" /> Edit</button>
              <button onClick={() => { if (confirm('Delete plan?')) api.deletePlan(p.id).then(load) }} className="btn-danger"><Trash2 className="h-3 w-3" /></button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
