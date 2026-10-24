import { MODE_TEXT, nf, type DataMode } from '../insights'
import type { DatasetsResponse, Message, Overview, QuickAction } from '../types'
import { ChartView } from './ChartView'
import { DataTable } from './DataTable'
import { ActionIcon, SourceIcon } from './Icons'
import { MlStatusCard, NextQuestionsCard, SourcesCard } from './InsightsPanel'

export function QuickActions({ actions, onAsk, disabled }: { actions: QuickAction[]; onAsk: (q: string) => void; disabled: boolean }) {
  return (
    <div className="chips" role="group" aria-label="Foreslåede spørgsmål">
      {actions.map((a) => (
        <button key={a.label} type="button" className="chip" onClick={() => onAsk(a.question)} disabled={disabled} title={a.question}>
          <ActionIcon icon={a.icon} /> {a.label}
        </button>
      ))}
    </div>
  )
}

export function Hero({ compact }: { compact?: boolean }) {
  return (
    <header className={`hero ${compact ? 'hero-compact' : ''}`}>
      <div className="eyebrow">Dit overblik</div>
      <h1>Fra data til indsigt.</h1>
      <p className="hero-sub">Spørg til måltider, indkøb og vaner.</p>
    </header>
  )
}

export function OverviewView({ overview, mode, questions, onAsk, onOpenSources, busy }: {
  overview: Overview | null; mode: DataMode | null; questions: string[]; onAsk: (q: string) => void
  onOpenSources: () => void; busy: boolean
}) {
  return (
    <div className="view">
      <Hero />
      <QuickActions actions={overview?.quick_actions ?? []} onAsk={onAsk} disabled={busy} />
      {mode && (
        <div className={`mode-explainer mode-${mode}`}>
          <strong>{MODE_TEXT[mode].badge}.</strong>{' '}
          {mode === 'real'
            ? 'Svarene bygger på pseudonymiserede MealMind-data med kun læseadgang. Brugere kendes kun som pseudonyme nøgler.'
            : 'Svarene bygger på syntetiske data genereret til afprøvning – ikke rigtige MealMind-brugere. ML-resultater er ikke produktionsklare.'}
        </div>
      )}
      <div className="overview-grid">
        <SourcesCard overview={overview} mode={mode} onOpen={onOpenSources} />
        <NextQuestionsCard questions={questions} onAsk={onAsk} disabled={busy} />
        <MlStatusCard overview={overview} />
      </div>
    </div>
  )
}

export function AnalysesView({ messages, onAsk, actions, busy }: { messages: Message[]; onAsk: (q: string) => void; actions: QuickAction[]; busy: boolean }) {
  const items: { question: string; id: string; node: React.ReactNode }[] = []
  let question = ''
  for (const m of messages) {
    if (m.role === 'user') question = m.text
    else for (const v of m.visuals) {
      items.push({ question, id: v.id, node: v.kind === 'chart' ? <ChartView spec={v.chart} /> : <DataTable spec={v.table} /> })
    }
  }
  return (
    <div className="view">
      <header className="view-head">
        <h1>Analyser</h1>
        <p className="muted">Grafer og tabeller fra den aktuelle samtale.</p>
      </header>
      {items.length === 0 ? (
        <div className="empty-card">
          <p>Ingen analyser endnu. Stil et spørgsmål, så samles graferne og tabellerne her.</p>
          <QuickActions actions={actions} onAsk={onAsk} disabled={busy} />
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

export function SourcesView({ datasets, overview, mode, focus }: {
  datasets: DatasetsResponse | null; overview: Overview | null; mode: DataMode | null; focus: string | null
}) {
  const titles = new Map(overview?.sources.map((s) => [s.table, s]) ?? [])
  return (
    <div className="view">
      <header className="view-head">
        <h1>Datakilder</h1>
        <p className="muted">
          {overview?.data_label ?? '…'}{mode ? ` · ${MODE_TEXT[mode].origin}` : ''}. Tabeller og kolonner, som AI-assistenten kan
          læse (kun læseadgang).
        </p>
      </header>
      {datasets?.tables.map((t) => {
        const info = titles.get(t.name)
        return (
          <details key={t.name} className="dataset" open={focus === t.name || datasets.tables.length <= 2}>
            <summary>
              <span className="round-icon"><SourceIcon kind={info?.kind ?? 'other'} /></span>
              <span className="dataset-title">{info?.title ?? t.name}</span>
              <code className="dataset-name">{t.name}</code>
              {t.row_count != null && <span className="muted">{nf.format(t.row_count)} rækker</span>}
            </summary>
            {t.description && <p className="dataset-desc">{t.description}</p>}
            <div className="table-scroll">
              <table className="columns-table">
                <thead><tr><th>Kolonne</th><th>Type</th><th>Beskrivelse / eksempler</th></tr></thead>
                <tbody>
                  {t.columns.map((c) => (
                    <tr key={c.name}>
                      <td><code>{c.name}</code></td>
                      <td className="muted">{c.type.toLowerCase()}</td>
                      <td>{c.description || <span className="muted">{c.sample_values.slice(0, 4).join(', ')}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )
      })}
      {datasets && (
        <section className="panel-card">
          <h2>ML-funktioner i AI-assistenten</h2>
          <ul className="fn-list">
            {datasets.ml_functions.map((f) => <li key={f.name}><code>{f.name}</code> <span className="muted">{f.description.split('. ')[0]}.</span></li>)}
          </ul>
        </section>
      )}
    </div>
  )
}
