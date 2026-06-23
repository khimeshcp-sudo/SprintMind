import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ListTodo, Clock, CheckCircle2, Loader2, Crown } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

function StatCard({ icon: Icon, label, value, color }) {
  const colors = {
    brand: 'from-brand-500/20 to-brand-600/5 border-brand-500/20 text-brand-300',
    yellow: 'from-yellow-500/20 to-yellow-600/5 border-yellow-500/20 text-yellow-300',
    blue: 'from-blue-500/20 to-blue-600/5 border-blue-500/20 text-blue-300',
    green: 'from-green-500/20 to-green-600/5 border-green-500/20 text-green-300',
  }
  return (
    <div className={`card border bg-gradient-to-br ${colors[color]}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-400">{label}</p>
          <p className="mt-1 text-3xl font-bold text-white">{value}</p>
        </div>
        <div className={`rounded-xl bg-surface-700/50 p-3`}>
          <Icon className="h-6 w-6" />
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadDashboard() {
      try {
        await api.syncBilling().catch(() => {})
        const [s, t] = await Promise.all([api.dashboard(), api.listTasks()])
        setStats(s)
        setTasks(t.slice(0, 5))
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    loadDashboard()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    )
  }

  const statusBadge = (status) => {
    const map = {
      pending: 'bg-yellow-500/20 text-yellow-300',
      in_progress: 'bg-blue-500/20 text-blue-300',
      completed: 'bg-green-500/20 text-green-300',
      failed: 'bg-red-500/20 text-red-300',
    }
    return <span className={`badge ${map[status] || map.pending}`}>{status.replace('_', ' ')}</span>
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="mt-1 text-gray-400">Welcome back, {user?.full_name}</p>
      </div>

      {stats?.plan_name && (
        <div className="card mb-6 flex items-center justify-between gap-4 border-brand-500/20 bg-gradient-to-r from-brand-600/10 to-transparent">
          <div className="flex items-center gap-4">
            <Crown className="h-8 w-8 text-brand-400" />
            <div>
              <p className="font-semibold text-brand-300">{stats.plan_name} Plan</p>
              <p className="text-sm text-gray-400">
                {stats.tasks_remaining !== null
                  ? `${stats.tasks_remaining} of ${stats.max_tasks} tasks remaining`
                  : 'Unlimited tasks'}
              </p>
              {!stats.is_active && (
                <p className="mt-1 text-sm text-red-400">Subscription inactive — upgrade in Billing.</p>
              )}
            </div>
          </div>
          {!stats.can_create_task && stats.is_active && (
            <Link to="/billing" className="btn-primary text-sm">Upgrade</Link>
          )}
        </div>
      )}

      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={ListTodo} label="Total Tasks" value={stats?.total_tasks ?? 0} color="brand" />
        <StatCard icon={Clock} label="Pending" value={stats?.pending_tasks ?? 0} color="yellow" />
        <StatCard icon={Loader2} label="In Progress" value={stats?.in_progress_tasks ?? 0} color="blue" />
        <StatCard icon={CheckCircle2} label="Completed" value={stats?.completed_tasks ?? 0} color="green" />
      </div>

      <div className="card">
        <h2 className="mb-4 text-lg font-semibold">Recent Tasks</h2>
        {tasks.length === 0 ? (
          <p className="py-8 text-center text-gray-500">No tasks yet. Head to My Tasks to create one.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-surface-600 text-gray-500">
                  <th className="pb-3 pr-4 font-medium">Title</th>
                  <th className="pb-3 pr-4 font-medium">Jira</th>
                  <th className="pb-3 pr-4 font-medium">Status</th>
                  <th className="pb-3 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id} className="border-b border-surface-600/50 hover:bg-surface-700/30">
                    <td className="py-3 pr-4 font-medium">{t.title}</td>
                    <td className="py-3 pr-4 text-gray-400">{t.jira_key || '—'}</td>
                    <td className="py-3 pr-4">{statusBadge(t.status)}</td>
                    <td className="py-3 text-gray-500">{new Date(t.created_at).toLocaleDateString()}</td>
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
