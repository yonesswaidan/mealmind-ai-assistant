import { MODE_TEXT, nf, type DataMode } from '../insights'
import type { MlStatus, Overview, SourceInfo } from '../types'
import { IconBulb, IconChevron, IconNetwork, SourceIcon } from './Icons'

function OriginDot({ mode }: { mode: DataMode }) {
  return (
    <span className={`origin origin-${mode}`}>
      <span className="dot" aria-hidden /> {MODE_TEXT[mode].origin}
    </span>
  )
}

export function SourcesCard({ overview, mode, onOpen }: { overview: Overview | null; mode: DataMode | null; onOpen: (s: SourceInfo) => void }) {
  const sources = overview?.sources.filter((s) => s.kind !== 'ml') ?? []
  return (
    <section className="panel-card" aria-labelledby="sources-title">
      <h2 id="sources-title">Dine datakilder</h2>
      {!overview && <p className="muted">Henter…</p>}
      <ul className="source-list">
        {sources.map((s) => (
          <li key={s.table}>
            <button type="button" className="source-row" onClick={() => onOpen(s)}>
              <span className="round-icon"><SourceIcon kind={s.kind} /></span>
              <span className="source-text">
                <span className="source-title">{s.title}</span>
                {s.rows != null && <span className="source-rows">{nf.format(s.rows)} rækker</span>}
              </span>
              {mode && <OriginDot mode={mode} />}
              <IconChevron size={18} className="chev" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function NextQuestionsCard({ questions, onAsk, disabled }: { questions: string[]; onAsk: (q: string) => void; disabled: boolean }) {
  if (questions.length === 0) return null
  return (
    <section className="panel-card" aria-labelledby="next-title">
      <h2 id="next-title">Næste gode spørgsmål</h2>
      <ul className="next-list">
        {questions.map((q) => (
          <li key={q}>
            <button type="button" className="next-row" onClick={() => onAsk(q)} disabled={disabled}>
              <span className="round-icon"><IconBulb /></span>
              <span>{q}</span>
              <IconChevron size={18} className="chev" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

const ML_SOURCE_TEXT: Record<MlStatus['source'], string> = {
  databricks: 'Trænet i Databricks',
  local_lakehouse: 'Trænet lokalt · MLflow',
  local: 'Beregnes på forespørgsel',
}

export function MlStatusCard({ overview }: { overview: Overview | null }) {
  const items = overview?.ml_status ?? []
  return (
    <section className="panel-card" aria-labelledby="ml-title">
      <h2 id="ml-title">ML-status</h2>
      {items.length === 0 && <p className="muted">{overview ? 'Ingen ML-funktioner tilgængelige.' : 'Henter…'}</p>}
      <ul className="ml-list">
        {items.map((m) => (
          <li key={m.name} className="ml-row" title={m.detail}>
            <span className="round-icon"><IconNetwork /></span>
            <span className="ml-text">
              <span className="ml-title">{m.title}</span>
              <span className="ml-detail">{ML_SOURCE_TEXT[m.source] ?? ML_SOURCE_TEXT.local}</span>
            </span>
            <span className={`pill pill-${m.label === 'Klar' ? 'ok' : m.label === 'Demo' ? 'demo' : 'neutral'}`}>{m.label}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

interface PanelProps {
  overview: Overview | null
  mode: DataMode | null
  questions: string[]
  onAsk: (q: string) => void
  onOpenSource: (s: SourceInfo) => void
  busy: boolean
}

export function InsightsPanel({ overview, mode, questions, onAsk, onOpenSource, busy }: PanelProps) {
  return (
    <div className="panel-stack">
      <SourcesCard overview={overview} mode={mode} onOpen={onOpenSource} />
      <NextQuestionsCard questions={questions} onAsk={onAsk} disabled={busy} />
      <MlStatusCard overview={overview} />
    </div>
  )
}
