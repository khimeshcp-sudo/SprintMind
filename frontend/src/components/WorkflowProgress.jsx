import { CheckCircle2, Circle, Loader2, XCircle, User } from 'lucide-react'

const ICONS = {
  file: '📄',
  brain: '🧠',
  user: '👤',
  code: '💻',
  test: '🧪',
  play: '▶️',
  rocket: '🚀',
  check: '✅',
  flag: '🏁',
}

function StepIcon({ status }) {
  if (status === 'completed') return <CheckCircle2 className="h-5 w-5 text-green-400" />
  if (status === 'running') return <Loader2 className="h-5 w-5 animate-spin text-brand-400" />
  if (status === 'failed') return <XCircle className="h-5 w-5 text-red-400" />
  return <Circle className="h-5 w-5 text-gray-600" />
}

export default function WorkflowProgress({ steps = [], progressPercent = 0, status, cancelMessage }) {
  return (
    <div className="space-y-6">
      <div>
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium text-gray-300">AI Pipeline Progress</span>
          <span className="text-brand-300">{progressPercent}%</span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-surface-700">
          <div
            className="h-full rounded-full bg-gradient-to-r from-brand-500 via-brand-400 to-emerald-400 transition-all duration-700 ease-out"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        {status === 'waiting_approval' && (
          <p className="mt-2 text-xs text-amber-300 animate-pulse">Waiting for your approval…</p>
        )}
        {status === 'running' && (
          <p className="mt-2 text-xs text-brand-300">AI agents are working…</p>
        )}
        {status === 'failed' && (
          <p className="mt-2 text-xs text-red-300">A workflow step failed — see errors below.</p>
        )}
        {status === 'cancelled' && (
          <p className="mt-2 text-xs text-orange-300">
            {cancelMessage || 'Workflow stopped.'}
          </p>
        )}
      </div>

      <ol className="relative space-y-0">
        {steps.map((step, i) => {
          const isApproval = step.id?.startsWith('approval') || step.id === 'merge_code'
          const isActive = step.status === 'running'
          const isDone = step.status === 'completed'
          const isFailed = step.status === 'failed'
          return (
            <li key={step.id} className="relative flex gap-4 pb-6 last:pb-0">
              {i < steps.length - 1 && (
                <span
                  className={`absolute left-[10px] top-6 h-full w-0.5 transition-colors duration-500 ${
                    isDone ? 'bg-green-500/50' : isFailed ? 'bg-red-500/50' : 'bg-surface-600'
                  }`}
                />
              )}
              <div className="relative z-10 mt-0.5">
                <StepIcon status={step.status} />
              </div>
              <div
                className={`flex-1 rounded-xl border px-4 py-3 transition-all duration-300 ${
                  isFailed
                    ? 'border-red-500/40 bg-red-500/10'
                    : isActive
                      ? 'border-brand-500/50 bg-brand-500/10 shadow-glow'
                      : isDone
                        ? 'border-green-500/20 bg-green-500/5'
                        : 'border-surface-600/50 bg-surface-800/50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-base">{ICONS[step.icon] || '•'}</span>
                  <span className={`text-sm font-medium ${isActive ? 'text-white' : isFailed ? 'text-red-200' : 'text-gray-300'}`}>
                    {step.label}
                  </span>
                  {isApproval && <User className="h-3.5 w-3.5 text-amber-400" />}
                </div>
                {isFailed && step.errors?.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-red-300">
                    {step.errors.map((err, j) => (
                      <li key={j} className="whitespace-pre-wrap break-words">• {err}</li>
                    ))}
                  </ul>
                )}
                {isActive && (
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-700">
                    <div className="h-full w-1/3 animate-[shimmer_1.2s_ease-in-out_infinite] rounded-full bg-brand-400" />
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
