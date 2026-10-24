import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { formatValue } from '../format'
import { MODE_TEXT, hasChartFor, planLabel, tableToChart, type DataMode } from '../insights'
import type { AssistantMessage, Cell, Message, Step, TableSpec } from '../types'
import { ChartView } from './ChartView'
import { DataTable } from './DataTable'
import { IconBars, IconDatabase, LeafLogo } from './Icons'

const TOOL_LABELS: Record<string, string> = {
  run_sql: 'SQL-forespørgsel',
  analyze_data: 'Statistik',
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

function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="steps">
      {steps.map((step) => (
        <li key={step.id} className={`step step-${step.status}`}>
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
      ))}
    </ol>
  )
}

function TableVisual({ msg, table, asChart }: { msg: AssistantMessage; table: TableSpec; asChart: boolean }) {
  const chart = asChart && !hasChartFor(msg, table) ? tableToChart(table) : null
  return chart ? <ChartView spec={chart} /> : <DataTable spec={table} />
}

function Assistant({ msg, mode }: { msg: AssistantMessage; mode: DataMode | null }) {
  const streaming = msg.status === 'streaming'
  const [showBasis, setShowBasis] = useState(false)
  const [asChart, setAsChart] = useState(false)
  const thinking = streaming && !msg.text && !msg.steps.some((s) => s.status === 'running')
  const running = msg.steps.find((s) => s.status === 'running')
  const label = planLabel(msg.plan)
  const chartable = msg.visuals.some((v) => v.kind === 'table' && !hasChartFor(msg, v.table) && tableToChart(v.table))
  const msgMode: DataMode | null = msg.demo === undefined ? mode : msg.demo ? (mode === 'test' ? 'test' : 'demo') : 'real'

  return (
    <article className="answer" aria-busy={streaming}>
      <header className="answer-head">
        <LeafLogo size={26} />
        <span className="answer-name">MealMind Insights</span>
        {label && <span className="plan-chip">{label}</span>}
      </header>

      {thinking && <div className="thinking"><span className="spinner" /> Undersøger data…</div>}
      {running && <div className="thinking"><span className="spinner" /> {TOOL_LABELS[running.tool] ?? running.tool}: {stepTitle(running)}</div>}

      {msg.text && (
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
        </div>
      )}

      {msg.visuals.length > 0 && (
        <div className="visuals">
          {msg.visuals.map((v) =>
            v.kind === 'chart'
              ? <ChartView key={v.id} spec={v.chart} />
              : <TableVisual key={v.id} msg={msg} table={v.table} asChart={asChart} />,
          )}
          {msgMode && <div className="visual-note">Baseret på {MODE_TEXT[msgMode].origin.toLowerCase()}</div>}
        </div>
      )}

      {msg.notices?.map((n) => <div key={n} className="notice-box" role="note">{n}</div>)}
      {msg.status === 'error' && <div className="error-box" role="alert">{msg.error}</div>}

      {msg.steps.length > 0 && (
        <div className="answer-actions">
          <button type="button" className="btn btn-outline" aria-expanded={showBasis} onClick={() => setShowBasis((s) => !s)}>
            <IconDatabase size={18} /> {showBasis ? 'Skjul datagrundlag' : 'Se datagrundlag'}
          </button>
          {chartable && (
            <button type="button" className="btn btn-outline" aria-pressed={asChart} onClick={() => setAsChart((s) => !s)}>
              <IconBars size={18} /> {asChart ? 'Vis som tabel' : 'Vis som graf'}
            </button>
          )}
        </div>
      )}
      {showBasis && <Steps steps={msg.steps} />}
    </article>
  )
}

export function MessageView({ msg, mode }: { msg: Message; mode: DataMode | null }) {
  if (msg.role === 'user') {
    return (
      <div className="question">
        <div className="bubble">{msg.text}</div>
      </div>
    )
  }
  return <Assistant msg={msg} mode={mode} />
}
