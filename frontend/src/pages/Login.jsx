import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Zap, Mail, Lock, ArrowRight } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function Login() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('demo@sprintmind.io')
  const [password, setPassword] = useState('demo123')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (user) return <Navigate to="/dashboard" replace />

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Left panel */}
      <div className="hidden w-1/2 flex-col justify-between bg-gradient-to-br from-brand-700 via-brand-800 to-surface-900 p-12 lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10 backdrop-blur">
            <Zap className="h-6 w-6 text-white" />
          </div>
          <span className="text-2xl font-bold text-white">SprintMind</span>
        </div>
        <div>
          <h2 className="text-4xl font-bold leading-tight text-white">
            Magento tasks,<br />managed smarter.
          </h2>
          <p className="mt-4 max-w-md text-lg text-brand-200">
            Upload Jira tasks, track progress, and scale with subscription-based plans.
          </p>
        </div>
        <p className="text-sm text-brand-300/60">© 2026 SprintMind Platform</p>
      </div>

      {/* Right panel */}
      <div className="flex flex-1 items-center justify-center bg-surface-900 p-8">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden flex items-center gap-2">
            <Zap className="h-6 w-6 text-brand-500" />
            <span className="text-xl font-bold">SprintMind</span>
          </div>
          <h1 className="text-2xl font-bold">Welcome back</h1>
          <p className="mt-1 text-gray-400">Sign in to your account</p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            {error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                {error}
              </div>
            )}
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-300">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <input className="input-field pl-10" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-300">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <input className="input-field pl-10" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
            </div>
            <button type="submit" className="btn-primary w-full" disabled={loading}>
              {loading ? 'Signing in...' : <>Sign in <ArrowRight className="h-4 w-4" /></>}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-gray-500">
            No account? <Link to="/register" className="font-medium text-brand-400 hover:text-brand-300">Create one</Link>
          </p>

          <div className="mt-8 rounded-xl border border-surface-600 bg-surface-800 p-4 text-xs text-gray-500">
            <p className="font-medium text-gray-400 mb-2">Demo accounts</p>
            <p>User: demo@sprintmind.io / demo123</p>
            <p>Admin: admin@sprintmind.io / admin123</p>
          </div>
        </div>
      </div>
    </div>
  )
}
