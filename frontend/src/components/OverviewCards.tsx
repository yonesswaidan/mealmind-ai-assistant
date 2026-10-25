import { nf } from '../insights'
import { mlLabel } from '../present'
import type { MlStatus, Overview } from '../types'
import { IconBulb, IconChevron, IconNetwork, SourceIcon } from './Icons'

/** De data, svarene bygger på - kun til orientering; AI-assistenten bruger alle tabeller internt. */
export function SourcesCard({ overview }: { overview: Overview | null }) {
  const sources = overview?.sources.filter((s) => s.kind !== 'ml') ?? []
  return (
    <section className="panel-card" aria-labelledby="sources-title">
      <h2 id="sources-title">Dine datakilder</h2>
      <p className="panel-sub">De data, AI-assistenten kan læse og analysere.</p>
      {!overview && <p className="muted">Henter…</p>}
      <ul className="row-list">
        {sources.map((s) => (
          <li key={s.table} className="row-static">
            <span className="round-icon"><SourceIcon kind={s.kind} /></span>
            <span className="row-text">
              <span className="row-title">{s.title}</span>
              {s.rows != null && <span className="row-sub">{nf.format(s.rows)} rækker</span>}
            </span>
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
      <h2 id="next-title">Gode spørgsmål at stille</h2>
      <p className="panel-sub">Klik for at sende spørgsmålet til AI-assistenten.</p>
      <ul className="row-list">
        {questions.map((q) => (
          <li key={q}>
            <button type="button" className="row-btn" onClick={() => onAsk(q)} disabled={disabled}>
              <span className="round-icon"><IconBulb /></span>
              <span className="row-text"><span className="row-title">{q}</span></span>
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
  local: 'Beregnes, når du spørger',
}

export function MlStatusCard({ overview }: { overview: Overview | null }) {
  const items = overview?.ml_status ?? []
  return (
    <section className="panel-card panel-wide" aria-labelledby="ml-title">
      <h2 id="ml-title">Machine learning</h2>
      <p className="panel-sub">Modeller, der finder mønstre, afvigelser og lignende retter.</p>
      {items.length === 0 && <p className="muted">{overview ? 'Ingen ML-funktioner tilgængelige.' : 'Henter…'}</p>}
      <ul className="row-list">
        {items.map((m) => {
          const label = mlLabel(m)
          return (
            <li key={m.name} className="row-static" title={m.detail}>
              <span className="round-icon"><IconNetwork /></span>
              <span className="row-text">
                <span className="row-title">{m.title}</span>
                <span className="row-sub">{ML_SOURCE_TEXT[m.source] ?? ML_SOURCE_TEXT.local}</span>
              </span>
              <span className={`pill ${label === 'Klar' || label === 'Trænet' ? 'pill-ok' : 'pill-neutral'}`}>{label}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
