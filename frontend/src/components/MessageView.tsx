import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { formatValue } from '../format'
import { hasChartFor, planLabel, tableToChart, type DataMode } from '../insights'
import { formatTime, splitAnswer } from '../present'
import type { AssistantMessage, Cell, Message, Step, TableSpec } from '../types'
import { ChartView } from './ChartView'
import { IconAlert, IconBars, IconBulb, IconDatabase, IconRefresh, IconSpark, LeafLogo } from './Icons'
import { TableResult } from './ResultCards'

const TOOL_LABELS: Record<string, string> = {
  run_sql: 'Henter data',
  analyze_data: 'Statistik',
  run_ml: 'Machine learning',
  create_chart: 'Graf',
  show_table: 'Oversigt',
}

const ML_LABELS: Record<string, string> = {
  forecast_timeseries: 'Prognose',
  segment_clusters: 'Segmentering',
  detect_anomalies: 'Afvigelser',
  predict_outcome: 'Forudsigelse',
  find_similar: 'Lignende retter',
}

function stepTitle(step: Step): string {
  const input = (step.input ?? {}) as Record<string, unknown>
  if (step.tool === 'run_ml' && typeof input.function === 'string') return ML_LABELS[input.function] ?? input.function
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
    <ol className="steps" aria-label="Datagrundlag">
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
  return chart ? <ChartView spec={chart} /> : <TableResult spec={table} />
}

function Markdown({ text }: { text: string }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>
}

function Working({ msg }: { msg: AssistantMessage }) {
  const running = msg.steps.find((s) => s.status === 'running')
  const label = running ? [TOOL_LABELS[running.tool] ?? running.tool, stepTitle(running)].filter(Boolean).join(': ') : 'Analyserer dine data'
  return (
    <div className="working" role="status">
      <span className="dots" aria-hidden><i /><i /><i /></span> {label}…
    </div>
  )
}

interface Props {
  msg: AssistantMessage
  mode: DataMode | null
  question?: string
  onRetry?: (question: string) => void
}

function Assistant({ msg, question, onRetry }: Props) {
  const streaming = msg.status === 'streaming'
  const [showBasis, setShowBasis] = useState(false)
  const [asChart, setAsChart] = useState(false)
  const label = planLabel(msg.plan)
  const chartable = msg.visuals.some((v) => v.kind === 'table' && !hasChartFor(msg, v.table) && tableToChart(v.table))
  const { body, insight, suggestions } = splitAnswer(msg.text)
  // Én graf/tabel og en indsigt står side om side (som på forsiden); ellers står indsigten under resultaterne.
  const sideBySide = msg.visuals.length === 1 && insight !== null

  const visuals = msg.visuals.map((v) =>
    v.kind === 'chart'
      ? <ChartView key={v.id} spec={v.chart} />
      : <TableVisual key={v.id} msg={msg} table={v.table} asChart={asChart} />,
  )
  const insightBox = insight && (
    <aside className="insight" aria-label="Vigtig indsigt">
      <div className="insight-head"><span className="insight-icon"><IconBulb size={18} /></span> Vigtig indsigt</div>
      <Markdown text={insight} />
    </aside>
  )

  return (
    <article className="exchange" aria-busy={streaming}>
      <div className="avatar" aria-hidden><LeafLogo size={22} /></div>
      <div className="exchange-body">
        <div className="exchange-meta">
          <span className="exchange-name">MealMind AI</span>
          {msg.createdAt && <time dateTime={new Date(msg.createdAt).toISOString()}>{formatTime(msg.createdAt)}</time>}
        </div>
        <div className="answer">
          <header className="answer-head">
            <div className="answer-heading">
              {question && <h2 className="answer-title">{question}</h2>}
              {label && <span className="plan-chip">{label}</span>}
            </div>
            {(msg.steps.length > 0 || chartable) && (
              <div className="answer-actions">
                {chartable && (
                  <button type="button" className="pill-btn" aria-pressed={asChart} onClick={() => setAsChart((s) => !s)}>
                    <IconBars size={16} /> {asChart ? 'Vis som tabel' : 'Vis som graf'}
                  </button>
                )}
                {msg.steps.length > 0 && (
                  <button type="button" className="pill-btn" aria-expanded={showBasis} onClick={() => setShowBasis((s) => !s)}>
                    <IconDatabase size={16} /> {showBasis ? 'Skjul datagrundlag' : 'Se datagrundlag'}
                  </button>
                )}
              </div>
            )}
          </header>

          {body && <Markdown text={body} />}
          {streaming && <Working msg={msg} />}

          {sideBySide ? (
            <div className="visual-insight">{visuals}{insightBox}</div>
          ) : (
            <>
              {visuals.length > 0 && <div className="visuals">{visuals}</div>}
              {insightBox}
            </>
          )}

          {suggestions && (
            <aside className="suggest-box" aria-label="Forslag til MealMind">
              <div className="insight-head"><span className="insight-icon"><IconSpark size={18} /></span> Forslag til MealMind</div>
              <Markdown text={suggestions} />
            </aside>
          )}

          {msg.notices?.map((n) => <div key={n} className="notice-box" role="note"><IconAlert size={16} /> {n}</div>)}
          {msg.status === 'error' && (
            <div className="error-box" role="alert">
              <IconAlert size={18} />
              <span className="error-text">{msg.error || 'Noget gik galt.'}</span>
              {question && onRetry && (
                <button type="button" className="pill-btn" onClick={() => onRetry(question)}><IconRefresh size={16} /> Prøv igen</button>
              )}
            </div>
          )}
          {showBasis && <Steps steps={msg.steps} />}
        </div>
      </div>
    </article>
  )
}

/** Spørgsmålet vises som titel på svarkortet, så brugerbeskeder renderes ikke selvstændigt. */
export function MessageView({ msg, mode, question, onRetry }: { msg: Message } & Omit<Props, 'msg'>) {
  if (msg.role === 'user') return null
  return <Assistant msg={msg} mode={mode} question={question} onRetry={onRetry} />
}
