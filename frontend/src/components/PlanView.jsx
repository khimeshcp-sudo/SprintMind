/** Renders AI plan markdown/text from workflow.plan */
export function formatPlanContent(plan) {
  if (!plan) return ''
  if (typeof plan === 'string') return plan
  if (plan.content) return plan.content
  if (plan.summary) return plan.summary
  return JSON.stringify(plan, null, 2)
}

export default function PlanView({ plan, revision = 0, className = '' }) {
  if (!plan) return null
  const text = formatPlanContent(plan)

  return (
    <div className={className}>
      <h3 className="mb-3 font-semibold">
        Implementation Plan
        {revision > 0 && (
          <span className="ml-2 text-xs font-normal text-amber-400">(revision {revision})</span>
        )}
      </h3>
      <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap text-sm text-gray-300">{text}</pre>
    </div>
  )
}
