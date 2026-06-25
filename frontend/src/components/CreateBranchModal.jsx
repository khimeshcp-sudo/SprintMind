import { useEffect, useState } from 'react'
import { GitBranch, Loader2 } from 'lucide-react'
import { api } from '../api/client'

const BRANCH_PATTERN =
  /^(?!-)(?!.*\.\.)(?!.*\/\/)(?!.*@\{)(?!.*[~^:?*[\]\\])(?!.*\s)(?!.*\.$)(?!.*\/$)[a-zA-Z0-9](?:[a-zA-Z0-9._/-]*[a-zA-Z0-9])?$/

function validateBranchNameLocal(name) {
  const trimmed = (name || '').trim()
  if (!trimmed) return 'Branch name is required.'
  if (trimmed.length > 255) return 'Branch name must be 255 characters or fewer.'
  if (trimmed.startsWith('-') || trimmed.endsWith('.') || trimmed.endsWith('/')) {
    return "Branch name cannot start with '-' or end with '.' or '/'."
  }
  if (trimmed.includes('..') || trimmed.includes('@{')) {
    return 'Branch name contains invalid characters or sequences.'
  }
  if (!BRANCH_PATTERN.test(trimmed)) {
    return (
      'Use only letters, numbers, hyphens, underscores, slashes, and dots. ' +
      'Avoid spaces and special characters (~, ^, :, ?, *, [, \\).'
    )
  }
  return null
}

export default function CreateBranchModal({ approval, onCreate, onSkip, loading }) {
  const [branchName, setBranchName] = useState('')
  const [error, setError] = useState('')
  const [validating, setValidating] = useState(false)

  const defaultBranchName = approval?.data?.default_branch_name || 'sm-new1'
  const serverError = approval?.data?.validation_error

  useEffect(() => {
    setBranchName('')
    setError(serverError || '')
  }, [approval?.gate, serverError])

  if (!approval || approval.gate !== 'create_branch') return null

  const handleCreate = async () => {
    const trimmed = branchName.trim()
    const localError = validateBranchNameLocal(trimmed)
    if (localError) {
      setError(localError)
      return
    }

    setValidating(true)
    setError('')
    try {
      const result = await api.validateBranchName(trimmed)
      if (!result.valid) {
        setError(result.error || 'Invalid branch name.')
        return
      }
      await onCreate(trimmed)
    } catch (err) {
      setError(err.message)
    } finally {
      setValidating(false)
    }
  }

  const busy = loading || validating

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="card w-full max-w-lg">
        <div className="mb-4 border-b border-surface-600 pb-4">
          <p className="text-xs uppercase tracking-wide text-brand-400">Workflow step</p>
          <h2 className="mt-1 flex items-center gap-2 text-xl font-bold">
            <GitBranch className="h-5 w-5 text-brand-400" />
            Create a New Branch
          </h2>
          <p className="mt-2 text-sm text-gray-400">
            Enter a custom branch name or skip to use the default name shown below.
          </p>
        </div>

        <div className="mb-4">
          <label htmlFor="branch-name" className="mb-1.5 block text-sm text-gray-400">
            Branch name
          </label>
          <input
            id="branch-name"
            type="text"
            className="input-field"
            placeholder="e.g. feature/my-change"
            value={branchName}
            disabled={busy}
            onChange={(e) => {
              setBranchName(e.target.value)
              if (error) setError('')
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !busy) handleCreate()
            }}
          />
        </div>

        <p className="mb-4 text-sm text-red-400">
          Note: If you skip this step, a default branch will be created automatically with the name:{' '}
          <strong className="font-semibold text-red-300">{defaultBranchName}</strong>
        </p>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          <button className="btn-primary flex-1" disabled={busy} onClick={handleCreate}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />}
            Create
          </button>
          <button className="btn-secondary flex-1" disabled={busy} onClick={() => onSkip()}>
            Skip
          </button>
        </div>
      </div>
    </div>
  )
}
