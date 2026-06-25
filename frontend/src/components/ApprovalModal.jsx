import { useState } from 'react'
import { Check, X, Loader2 } from 'lucide-react'

export default function ApprovalModal({ approval, onDecide, loading }) {
  const [feedback, setFeedback] = useState('')

  if (!approval) return null

  const { title, message, data, gate } = approval

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="card max-h-[90vh] w-full max-w-2xl overflow-y-auto">
        <div className="mb-4 border-b border-surface-600 pb-4">
          <p className="text-xs uppercase tracking-wide text-amber-400">Human approval required</p>
          <h2 className="mt-1 text-xl font-bold">{title}</h2>
          <p className="mt-2 text-sm text-gray-400">{message}</p>
        </div>

        <div className="mb-6 max-h-64 overflow-y-auto rounded-xl border border-surface-600 bg-surface-900/80 p-4">
          <pre className="whitespace-pre-wrap break-words text-xs text-gray-300">
            {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
          </pre>
        </div>

        <div className="mb-4">
          <label className="mb-1.5 block text-sm text-gray-400">Feedback (optional)</label>
          <textarea
            className="input-field min-h-[80px] resize-y"
            placeholder="Request changes or add notes…"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            className="btn-primary flex-1"
            disabled={loading}
            onClick={() => onDecide(true, feedback, gate)}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Approve &amp; Continue
          </button>
          <button
            className="btn-danger flex-1"
            disabled={loading}
            onClick={() => onDecide(false, feedback, gate)}
          >
            <X className="h-4 w-4" /> Reject / Revise
          </button>
        </div>
        <p className="mt-3 text-center text-xs text-gray-500">Step: {gate}</p>
      </div>
    </div>
  )
}
