import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Bot,
  Loader2,
  Play,
  RefreshCw,
  FileText,
  Paperclip,
  Square,
  RotateCcw,
} from 'lucide-react'
import { api } from '../api/client'
import WorkflowProgress from '../components/WorkflowProgress'
import ApprovalModal from '../components/ApprovalModal'
import PlanView from '../components/PlanView'

function statusBadge(status) {
  const map = {
    pending: 'bg-yellow-500/20 text-yellow-300',
    in_progress: 'bg-blue-500/20 text-blue-300',
    completed: 'bg-green-500/20 text-green-300',
    failed: 'bg-red-500/20 text-red-300',
    cancelled: 'bg-orange-500/20 text-orange-300',
    running: 'bg-blue-500/20 text-blue-300',
    waiting_approval: 'bg-amber-500/20 text-amber-300',
  }
  return (
    <span className={`badge ${map[status] || 'bg-gray-500/20 text-gray-300'}`}>
      {(status || 'unknown').replace(/_/g, ' ')}
    </span>
  )
}

export default function TaskDetail() {
  const { id } = useParams()
  const [task, setTask] = useState(null)
  const [workflow, setWorkflow] = useState(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState('')

  const loadTask = useCallback(async () => {
    const t = await api.getTask(id)
    setTask(t)
    return t
  }, [id])

  const [polling, setPolling] = useState(false)

  const loadWorkflow = useCallback(async () => {
    try {
      const w = await api.getWorkflow(id)
      setWorkflow(w)
      if (w.status === 'completed' || w.status === 'failed' || w.status === 'cancelled') {
        setPolling(false)
      }
      return w
    } catch {
      return null
    }
  }, [id])

  const refresh = useCallback(async () => {
    setError('')
    try {
      await loadTask()
      await loadWorkflow()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [loadTask, loadWorkflow])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    const shouldPoll =
      polling ||
      actionLoading ||
      workflow?.status === 'running' ||
      workflow?.status === 'waiting_approval'
    if (!shouldPoll) return

    loadWorkflow().catch(() => {})
    const timer = setInterval(() => {
      loadWorkflow().catch(() => {})
    }, 1000)
    return () => clearInterval(timer)
  }, [polling, actionLoading, workflow?.status, loadWorkflow])

  const startFlow = async () => {
    setActionLoading(true)
    setPolling(true)
    setError('')
    try {
      const stepDefs = await api.workflowSteps().catch(() => [])
      setWorkflow({
        status: 'running',
        progress_percent: 0,
        current_step: 'parse_requirement',
        steps: stepDefs.map((s) => ({
          ...s,
          status: s.id === 'parse_requirement' ? 'running' : 'pending',
        })),
        waiting_approval: null,
      })
      const w = await api.startWorkflow(id)
      setWorkflow(w)
      await loadTask()
    } catch (err) {
      setError(err.message)
      setPolling(false)
    } finally {
      setActionLoading(false)
    }
  }

  const stopFlow = async () => {
    setActionLoading(true)
    setError('')
    try {
      const w = await api.stopWorkflow(id)
      setWorkflow(w)
      setPolling(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setActionLoading(false)
    }
  }

  const restartFlow = async () => {
    setActionLoading(true)
    setPolling(true)
    setError('')
    try {
      const stepDefs = await api.workflowSteps().catch(() => [])
      setWorkflow({
        status: 'running',
        progress_percent: 0,
        current_step: 'parse_requirement',
        steps: stepDefs.map((s) => ({
          ...s,
          status: s.id === 'parse_requirement' ? 'running' : 'pending',
        })),
        waiting_approval: null,
      })
      const w = await api.restartWorkflow(id)
      setWorkflow(w)
      await loadTask()
    } catch (err) {
      setError(err.message)
      setPolling(false)
    } finally {
      setActionLoading(false)
    }
  }

  const handleApproval = async (approved, feedback) => {
    setActionLoading(true)
    setPolling(true)
    setError('')
    try {
      const w = await api.resumeWorkflow(id, { approved, feedback })
      setWorkflow(w)
      if (w.status === 'completed') {
        setPolling(false)
        await loadTask()
      }
    } catch (err) {
      setError(err.message)
      setPolling(false)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-10 w-10 animate-spin text-brand-500" />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="text-center py-24">
        <p className="text-gray-400">Task not found</p>
        <Link to="/tasks" className="btn-secondary mt-4 inline-flex">Back to tasks</Link>
      </div>
    )
  }

  const isActive =
    workflow?.status === 'running' || workflow?.status === 'waiting_approval'
  const canStart =
    !workflow ||
    workflow.status === 'completed' ||
    workflow.status === 'failed' ||
    workflow.status === 'cancelled'

  const approvalPayload = workflow?.waiting_approval || null

  return (
    <div>
      <ApprovalModal
        approval={approvalPayload}
        onDecide={handleApproval}
        loading={actionLoading}
      />

      <div className="mb-6">
        <Link to="/tasks" className="inline-flex items-center gap-2 text-sm text-gray-400 hover:text-brand-300">
          <ArrowLeft className="h-4 w-4" /> Back to tasks
        </Link>
      </div>

      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <Bot className="h-8 w-8 text-brand-400" />
            <h1 className="text-3xl font-bold">{task.title}</h1>
          </div>
          {task.jira_key && (
            <p className="mt-1 text-sm text-brand-300">{task.jira_key}</p>
          )}
          <p className="mt-3 max-w-2xl text-gray-400">{task.description || 'No description'}</p>
          <div className="mt-4 flex flex-wrap gap-3 text-sm text-gray-500">
            <span className="flex items-center gap-1.5">
              <FileText className="h-4 w-4" /> Task status: {statusBadge(task.status)}
            </span>
            {task.file_name && (
              <span className="flex items-center gap-1.5">
                <Paperclip className="h-4 w-4" /> {task.file_name}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <button className="btn-secondary" onClick={refresh} disabled={actionLoading}>
            <RefreshCw className={`h-4 w-4 ${actionLoading ? 'animate-spin' : ''}`} /> Refresh
          </button>
          {isActive && (
            <button className="btn-secondary text-orange-300" onClick={stopFlow} disabled={actionLoading}>
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-4 w-4" />
              )}
              Stop Flow
            </button>
          )}
          {workflow && (
            <button className="btn-secondary" onClick={restartFlow} disabled={actionLoading}>
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="h-4 w-4" />
              )}
              Restart from Start
            </button>
          )}
          {canStart && !workflow && (
            <button className="btn-primary" onClick={startFlow} disabled={actionLoading}>
              {actionLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Start AI Flow
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {workflow?.session_error && (
        <div className="mb-6 rounded-xl border border-orange-500/30 bg-orange-500/10 px-4 py-3 text-sm text-orange-300">
          {workflow.session_error}
        </div>
      )}

      {workflow?.status === 'running' && workflow?.current_step === 'generate_plan' && (
        <div className="mb-6 rounded-xl border border-brand-500/30 bg-brand-500/10 px-4 py-3 text-sm text-brand-200">
          Generating plan with AI — local Ollama can take 1–3 minutes on CPU. For faster results, set{' '}
          <code className="text-brand-300">LLM_PROVIDER=groq</code> in <code className="text-brand-300">.env</code>.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="card lg:col-span-3">
          <h2 className="mb-6 text-lg font-semibold">LangGraph AI Pipeline</h2>
          {workflow ? (
            <WorkflowProgress
              steps={workflow.steps}
              progressPercent={workflow.progress_percent}
              status={workflow.status}
              cancelMessage={workflow.cancel_message}
            />
          ) : (
            <div className="py-12 text-center text-gray-500">
              <Bot className="mx-auto mb-4 h-12 w-12 text-surface-600" />
              <p>No workflow started yet.</p>
              <p className="mt-2 text-sm">
                Click <strong>Start AI Flow</strong> to read the CSV description, send it to AI for a plan,
                then continue with code, tests, and deploy.
              </p>
            </div>
          )}
        </div>

        <div className="space-y-6 lg:col-span-2">
          {workflow?.plan && (
            <div className="card">
              <PlanView plan={workflow.plan} revision={workflow.plan_revision || 0} />
            </div>
          )}
          {workflow?.test_results && (
            <div className="card">
              <h3 className="mb-3 font-semibold">Test Results</h3>
              <p className="text-sm text-green-400">
                {workflow.test_results.passed}/{workflow.test_results.total} passed
              </p>
              <p className="mt-1 text-xs text-gray-500">{workflow.test_results.output}</p>
            </div>
          )}
          {workflow?.staging_deploy && (
            <div className="card">
              <h3 className="mb-3 font-semibold">Staging Deploy</h3>
              <pre className="max-h-32 overflow-y-auto text-xs text-gray-400">
                {workflow.staging_deploy.log}
              </pre>
            </div>
          )}
          {workflow?.production_deploy && (
            <div className="card">
              <h3 className="mb-3 font-semibold">Production Deploy</h3>
              <pre className="max-h-32 overflow-y-auto text-xs text-gray-400">
                {workflow.production_deploy.log}
              </pre>
            </div>
          )}
          {workflow?.merge_request_url && (
            <div className="card">
              <h3 className="mb-3 font-semibold">Merge Request</h3>
              <a
                href={workflow.merge_request_url}
                target="_blank"
                rel="noreferrer"
                className="text-brand-300 hover:underline"
              >
                {workflow.merge_request_url}
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
