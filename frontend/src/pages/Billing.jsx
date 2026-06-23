import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Crown, Loader2, CreditCard, Zap, AlertTriangle } from 'lucide-react'
import { api } from '../api/client'

function formatPrice(cents) {
  if (cents === 0) return 'Free'
  return `$${(cents / 100).toFixed(0)}/mo`
}

export default function Billing() {
  const [searchParams] = useSearchParams()
  const [plans, setPlans] = useState([])
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(searchParams.get('success') === '1')

  const [verifying, setVerifying] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [p, s] = await Promise.all([api.listPlans(), api.billingStatus()])
      setPlans(p.filter((plan) => plan.is_active))
      setStatus(s)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    async function init() {
      const sessionId = searchParams.get('session_id')
      setVerifying(true)
      try {
        if (searchParams.get('success') === '1' && sessionId) {
          const result = await api.verifyCheckoutSession(sessionId)
          setSuccess(true)
          setError('')
          setStatus((prev) => ({
            ...prev,
            plan_name: result.plan_name,
            status: result.status,
            is_active: true,
          }))
        } else {
          await api.syncBilling().catch(() => {})
        }
      } catch (err) {
        setError(err.message)
      } finally {
        setVerifying(false)
      }
      await load()
    }
    init()
  }, [])

  const handleUpgrade = async (planId) => {
    setError('')
    setActionLoading(planId)
    try {
      const result = await api.checkout(planId)
      if (result.activated) {
        setSuccess(true)
        await load()
      } else if (result.checkout_url) {
        window.location.href = result.checkout_url
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setActionLoading(null)
    }
  }

  const handlePortal = async () => {
    setError('')
    setActionLoading('portal')
    try {
      const { portal_url } = await api.billingPortal()
      window.location.href = portal_url
    } catch (err) {
      setError(err.message)
    } finally {
      setActionLoading(null)
    }
  }

  if (loading || verifying) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-32">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
        {verifying && <p className="text-sm text-gray-400">Activating your subscription...</p>}
      </div>
    )
  }

  const currentPlanId = status?.plan_id

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Billing & Plans</h1>
        <p className="mt-1 text-gray-400">Manage your subscription and usage limits</p>
      </div>

      {success && (
        <div className="card mb-6 flex items-center gap-3 border-green-500/30 bg-green-500/10 text-green-300">
          <Check className="h-5 w-5" />
          Payment successful! Your plan is now active.
        </div>
      )}

      {error && (
        <div className="card mb-6 flex items-center gap-3 border-red-500/30 bg-red-500/10 text-red-300">
          <AlertTriangle className="h-5 w-5" />
          {error}
        </div>
      )}

      {status && (
        <div className="card mb-8 border-brand-500/20 bg-gradient-to-r from-brand-600/10 to-transparent">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <Crown className="h-10 w-10 text-brand-400" />
              <div>
                <p className="text-lg font-semibold text-white">{status.plan_name || 'No plan'} Plan</p>
                <p className="text-sm text-gray-400">
                  Status: <span className={status.is_active ? 'text-green-400' : 'text-red-400'}>{status.status}</span>
                  {status.tasks_remaining !== null && (
                    <> · {status.task_count}/{status.max_tasks} tasks used</>
                  )}
                </p>
                {!status.can_create_task && (
                  <p className="mt-1 text-sm text-yellow-400">Task limit reached — upgrade to continue.</p>
                )}
                {status.cancel_at_period_end && (
                  <p className="mt-1 text-sm text-yellow-400">Cancels at end of billing period.</p>
                )}
              </div>
            </div>
            {status.stripe_subscription_id && (
              <button className="btn-secondary" onClick={handlePortal} disabled={actionLoading === 'portal'}>
                <CreditCard className="h-4 w-4" />
                {actionLoading === 'portal' ? 'Loading...' : 'Manage Billing'}
              </button>
            )}
            <button
              className="btn-secondary"
              onClick={async () => { setActionLoading('sync'); await api.syncBilling(); await load(); setActionLoading(null) }}
              disabled={actionLoading === 'sync'}
            >
              {actionLoading === 'sync' ? 'Syncing...' : 'Sync Plan'}
            </button>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {plans.map((plan) => {
          const isCurrent = plan.id === currentPlanId
          const isUpgrade = plan.price_monthly > (plans.find((p) => p.id === currentPlanId)?.price_monthly ?? -1)
          return (
            <div
              key={plan.id}
              className={`card relative flex flex-col ${isCurrent ? 'border-brand-500/50 ring-1 ring-brand-500/30' : ''}`}
            >
              {isCurrent && (
                <span className="absolute -top-3 left-4 badge bg-brand-500/20 text-brand-300">Current plan</span>
              )}
              <div className="mb-4 mt-2">
                <div className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-brand-400" />
                  <h3 className="text-xl font-bold">{plan.name}</h3>
                </div>
                <p className="mt-2 text-3xl font-bold text-white">{formatPrice(plan.price_monthly)}</p>
                <p className="mt-2 text-sm text-gray-400">{plan.description}</p>
              </div>
              <ul className="mb-6 flex-1 space-y-2 text-sm text-gray-300">
                <li className="flex items-center gap-2"><Check className="h-4 w-4 text-green-400" /> {plan.max_tasks} tasks</li>
                <li className="flex items-center gap-2"><Check className="h-4 w-4 text-green-400" /> {plan.max_users} team seats</li>
              </ul>
              <button
                className={isCurrent ? 'btn-secondary w-full' : 'btn-primary w-full'}
                disabled={isCurrent || actionLoading === plan.id}
                onClick={() => handleUpgrade(plan.id)}
              >
                {actionLoading === plan.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isCurrent ? (
                  'Current Plan'
                ) : isUpgrade ? (
                  'Upgrade'
                ) : plan.price_monthly === 0 ? (
                  'Switch to Free'
                ) : (
                  'Subscribe'
                )}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
