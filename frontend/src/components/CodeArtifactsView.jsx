import { useMemo, useState } from 'react'

const TYPE_STYLES = {
  backend: 'bg-blue-500/20 text-blue-300',
  frontend: 'bg-purple-500/20 text-purple-300',
  config: 'bg-gray-500/20 text-gray-300',
  test: 'bg-green-500/20 text-green-300',
  docs: 'bg-amber-500/20 text-amber-300',
}

function fileContent(artifact) {
  return artifact?.content || artifact?.preview || ''
}

export default function CodeArtifactsView({ data }) {
  const artifacts = useMemo(() => {
    if (!data) return []
    if (Array.isArray(data)) return data
    return data.artifacts || []
  }, [data])

  const [activeIndex, setActiveIndex] = useState(0)

  if (!artifacts.length) {
    return <p className="text-sm text-gray-500">No generated files to preview.</p>
  }

  const active = artifacts[Math.min(activeIndex, artifacts.length - 1)]
  const content = fileContent(active)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {artifacts.map((artifact, index) => {
          const path = artifact.relative_path || artifact.path || `file-${index + 1}`
          const type = artifact.type || 'code'
          const isActive = index === activeIndex
          return (
            <button
              key={`${path}-${index}`}
              type="button"
              onClick={() => setActiveIndex(index)}
              className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                isActive
                  ? 'border-brand-500 bg-brand-500/10 text-brand-200'
                  : 'border-surface-600 bg-surface-900/60 text-gray-400 hover:border-surface-500'
              }`}
            >
              <span className={`badge mb-1 ${TYPE_STYLES[type] || TYPE_STYLES.config}`}>{type}</span>
              <div className="max-w-[220px] truncate font-mono">{path}</div>
            </button>
          )
        })}
      </div>

      <div className="rounded-xl border border-surface-600 bg-surface-950/80">
        <div className="flex items-center justify-between border-b border-surface-600 px-4 py-2">
          <p className="truncate font-mono text-sm text-gray-200">
            {active.relative_path || active.path}
          </p>
          <span className={`badge ${TYPE_STYLES[active.type] || TYPE_STYLES.config}`}>
            {active.type || 'code'}
          </span>
        </div>
        <pre className="max-h-96 overflow-auto p-4 text-xs leading-relaxed text-gray-300">
          <code>{content}</code>
        </pre>
      </div>
    </div>
  )
}
