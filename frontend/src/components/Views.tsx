import { nf } from '../insights'
import type { Suggestion } from '../present'
import type { Message, Overview } from '../types'
import { ChartView } from './ChartView'
import { IconChat, IconDatabase, IconLayers, IconNetwork, SuggestionIcon } from './Icons'
import { MlStatusCard, NextQuestionsCard, SourcesCard } from './OverviewCards'
import { TableResult } from './ResultCards'

export function SuggestionCards({ items, onAsk, disabled }: { items: Suggestion[]; onAsk: (q: string) => void; disabled: boolean }) {
  if (items.length === 0) return null
  return (
    <div className="suggestions" role="group" aria-label="Foreslåede spørgsmål">
      {items.map((s) => (
        <button key={s.question} type="button" className="suggestion" onClick={() => onAsk(s.question)} disabled={disabled}
          title={s.question}>
          <span className="suggestion-icon"><SuggestionIcon icon={s.icon} /></span>
          <span className="suggestion-text">{s.label}</span>
        </button>
      ))}
    </div>
  )
}

/** Diskrete, dekorative blade øverst til højre - samme grønne toner som logoet. */
function HeroLeaves() {
  return (
    <svg className="hero-leaves" viewBox="0 0 320 260" aria-hidden focusable="false">
      <defs>
        <linearGradient id="leafA" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="var(--leaf-light)" stopOpacity="0.05" />
          <stop offset="1" stopColor="var(--leaf-light)" stopOpacity="0.55" />
        </linearGradient>
        <linearGradient id="leafB" x1="1" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="var(--leaf-dark)" stopOpacity="0.1" />
          <stop offset="1" stopColor="var(--leaf-light)" stopOpacity="0.35" />
        </linearGradient>
      </defs>
      <path d="M210 250c-10-90 20-170 100-230 14 100-22 190-100 230Z" fill="url(#leafA)" />
      <path d="M210 250C228 170 262 100 306 24" stroke="var(--leaf-light)" strokeOpacity="0.35" strokeWidth="1.5" fill="none" />
      <path d="M150 230c-50-40-70-100-50-170 60 30 85 95 50 170Z" fill="url(#leafB)" />
    </svg>
  )
}

export function Hero({ compact }: { compact?: boolean }) {
  return (
    <header className={`hero ${compact ? 'hero-compact' : ''}`}>
      <HeroLeaves />
      <div className="eyebrow">Din AI-assistent til madindsigt</div>
      <h1>Få mere ud af dine <span className="accent-text">måltidsdata</span></h1>
      <p className="hero-sub">
        Stil spørgsmål på almindeligt sprog, og få indsigt i måltider, indkøb, ernæring og brugere.
        {!compact && <> MealMind Insights omsætter dine data til klare svar og handlinger.</>}
      </p>
    </header>
  )
}

function PageHead({ title, sub }: { title: string; sub: string }) {
  return (
    <header className="page-head">
      <h1>{title}</h1>
      <p>{sub}</p>
    </header>
  )
}

export function OverviewView({ overview, questions, onAsk, busy }: {
  overview: Overview | null; questions: string[]; onAsk: (q: string) => void; busy: boolean
}) {
  const data = overview?.sources.filter((s) => s.kind !== 'ml') ?? []
  const rows = data.reduce((sum, s) => sum + (s.rows ?? 0), 0)
  const models = overview?.ml_status.length ?? 0
  const tiles = [
    { label: 'Datasæt', value: overview ? nf.format(data.length) : '–', Icon: IconDatabase },
    { label: 'Registreringer i alt', value: overview ? nf.format(rows) : '–', Icon: IconLayers },
    { label: 'ML-modeller', value: overview ? nf.format(models) : '–', Icon: IconNetwork },
  ]
  return (
    <div className="page">
      <PageHead title="Overblik" sub="Hvad MealMind Insights kan svare på, og hvilke data svarene bygger på." />
      <ul className="tile-row">
        {tiles.map(({ label, value, Icon }) => (
          <li key={label} className="tile">
            <span className="round-icon"><Icon /></span>
            <span className="tile-text">
              <span className="tile-value">{value}</span>
              <span className="tile-label">{label}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="overview-grid">
        <NextQuestionsCard questions={questions} onAsk={onAsk} disabled={busy} />
        <SourcesCard overview={overview} />
        <MlStatusCard overview={overview} />
      </div>
    </div>
  )
}

export function AnalysesView({ messages, onAsk, suggestions, busy }: {
  messages: Message[]; onAsk: (q: string) => void; suggestions: Suggestion[]; busy: boolean
}) {
  const items: { question: string; id: string; node: React.ReactNode }[] = []
  let question = ''
  for (const m of messages) {
    if (m.role === 'user') question = m.text
    else for (const v of m.visuals) {
      items.push({ question, id: v.id, node: v.kind === 'chart' ? <ChartView spec={v.chart} /> : <TableResult spec={v.table} /> })
    }
  }
  return (
    <div className="page">
      <PageHead title="Analyser" sub="Alle grafer og oversigter fra den aktuelle samtale samlet ét sted." />
      {items.length === 0 ? (
        <div className="empty-card">
          <span className="round-icon"><IconChat /></span>
          <p>Ingen analyser endnu. Stil et spørgsmål, så samles graferne og oversigterne her.</p>
          <SuggestionCards items={suggestions} onAsk={onAsk} disabled={busy} />
        </div>
      ) : (
        <div className="analysis-grid">
          {items.map((it) => (
            <section key={it.id} className="analysis-item">
              <div className="analysis-question">{it.question}</div>
              {it.node}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
