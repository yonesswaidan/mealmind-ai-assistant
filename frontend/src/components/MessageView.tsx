import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { formatValue } from '../format'
import type { AssistantMessage, Cell, Message, Step } from '../types'
import { ChartView } from './ChartView'
import { DataTable } from './DataTable'

const TOOL_LABELS: Record<string, string> = {
  run_sql: 'SQL-forespørgsel',
  analyze_data: 'Analyse',
  run_ml: 'ML-model',
  create_chart: 'Graf',
  show_table: 'Tabel',
}

function stepTitle(step: Step): string {
  const input = (step.input ?? {}) as Record<string, unknown>
  if (step.tool === 'run_ml' && typeof input.function === 'string') return input.function
  if (step.tool === 'analyze_data' && typeof input.operation === 'string') return String(input.title ?? input.operation)
  return typeof input.title === 'string' ? input.title : ''
}

function MlSummary({ summary }: { summary: Record<string, unknown> }) {
  const entries = Object.entries(summary).filter(([, v]) => v === null || typeof v !== 'object')
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{formatValue(v as Cell)}</dd>
        </div>
      ))}
    </dl>
  )
}

function StepItem({ step }: { step: Step }) {
  return (
    <li className={`step step-${step.status}`}>
      <div className="step-line">
        <span className="step-icon" aria-label={step.status}>
          {step.status === 'running' ? <span className="spinner" /> : step.status === 'ok' ? '✓' : '!'}
        </span>
        <span className="step-tool">{TOOL_LABELS[step.tool] ?? step.tool}</span>
        <span className="step-title">{stepTitle(step)}</span>
        {step.summary && <span className="step-summary">{step.summary}</span>}
      </div>
      {step.sql && <pre className="code"><code>{step.sql}</code></pre>}
      {step.ml && <MlSummary summary={step.ml.summary} />}
    </li>
  )
}

function Steps({ steps, streaming }: { steps: Step[]; streaming: boolean }) {
  if (!steps.length) return null
  const failed = steps.filter((s) => s.status === 'error').length
  return (
    <details className="steps" open={streaming}>
      <summary>
        Sådan fandt jeg svaret · {steps.length} trin{failed ? ` (${failed} rettet undervejs)` : ''}
      </summary>
      <ol>{steps.map((s) => <StepItem key={s.id} step={s} />)}</ol>
    </details>
  )
}

function Assistant({ msg }: { msg: AssistantMessage }) {
  const streaming = msg.status === 'streaming'
  const thinking = streaming && !msg.text && !msg.steps.some((s) => s.status === 'running')
  return (
    <article className="msg msg-assistant" aria-busy={streaming}>
      <div className="avatar" aria-hidden>MM</div>
      <div className="msg-body">
        <Steps steps={msg.steps} streaming={streaming} />
        {thinking && <div className="thinking"><span className="spinner" /> Tænker…</div>}
        {msg.text && (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
          </div>
        )}
        {msg.visuals.map((v) =>
          v.kind === 'chart' ? <ChartView key={v.id} spec={v.chart} /> : <DataTable key={v.id} spec={v.table} />,
        )}
        {msg.status === 'error' && <div className="error-box" role="alert">{msg.error}</div>}
      </div>
    </article>
  )
}

export function MessageView({ msg }: { msg: Message }) {
  if (msg.role === 'user') {
    return (
      <article className="msg msg-user">
        <div className="bubble">{msg.text}</div>
      </article>
    )
  }
  return <Assistant msg={msg} />
}
