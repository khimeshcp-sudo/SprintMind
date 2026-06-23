import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, ListTodo, Users, CreditCard, Layers, LogOut, Zap, Shield,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'

const navLinkClass = ({ isActive }) =>
  `flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition ${
    isActive
      ? 'bg-brand-600/20 text-brand-300 border border-brand-500/30'
      : 'text-gray-400 hover:bg-surface-700 hover:text-gray-200'
  }`

export default function Layout() {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex min-h-screen bg-surface-900">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-surface-600/60 bg-surface-800/90 backdrop-blur-xl">
        <div className="flex items-center gap-3 border-b border-surface-600/60 px-6 py-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-glow">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight">SprintMind</h1>
            <p className="text-xs text-gray-500">Magento Task SaaS</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-4">
          <p className="mb-2 px-4 text-xs font-semibold uppercase tracking-wider text-gray-600">Main</p>
          <NavLink to="/dashboard" className={navLinkClass}>
            <LayoutDashboard className="h-4 w-4" /> Dashboard
          </NavLink>
          <NavLink to="/tasks" className={navLinkClass}>
            <ListTodo className="h-4 w-4" /> My Tasks
          </NavLink>
          <NavLink to="/billing" className={navLinkClass}>
            <CreditCard className="h-4 w-4" /> Billing
          </NavLink>

          {isAdmin && (
            <>
              <p className="mb-2 mt-6 px-4 text-xs font-semibold uppercase tracking-wider text-gray-600">Admin</p>
              <NavLink to="/admin/users" className={navLinkClass}>
                <Users className="h-4 w-4" /> Users
              </NavLink>
              <NavLink to="/admin/plans" className={navLinkClass}>
                <Layers className="h-4 w-4" /> Plans
              </NavLink>
              <NavLink to="/admin/subscriptions" className={navLinkClass}>
                <CreditCard className="h-4 w-4" /> Subscriptions
              </NavLink>
            </>
          )}
        </nav>

        <div className="border-t border-surface-600/60 p-4">
          <div className="mb-3 flex items-center gap-3 rounded-xl bg-surface-700/50 px-3 py-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-600/30 text-sm font-bold text-brand-300">
              {user?.full_name?.[0]?.toUpperCase() || 'U'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{user?.full_name}</p>
              <p className="flex items-center gap-1 truncate text-xs text-gray-500">
                {isAdmin && <Shield className="h-3 w-3 text-brand-400" />}
                {user?.email}
              </p>
            </div>
          </div>
          <button onClick={handleLogout} className="btn-secondary w-full">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="ml-64 flex-1">
        <div className="pointer-events-none fixed inset-0 ml-64 overflow-hidden">
          <div className="absolute -right-40 -top-40 h-96 w-96 rounded-full bg-brand-600/10 blur-3xl" />
          <div className="absolute -bottom-20 right-1/3 h-72 w-72 rounded-full bg-purple-600/10 blur-3xl" />
        </div>
        <div className="relative p-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
