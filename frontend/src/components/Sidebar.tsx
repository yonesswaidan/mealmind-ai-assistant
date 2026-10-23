import { sourceBadge } from '../format'
import type { DatasetsResponse, Health } from '../types'

interface Props {
  health: Health | null
  datasets: DatasetsResponse | null
  onNewChat: () => void
  open: boolean
  onClose: () => void
}

const nf = new Intl.NumberFormat('da-DK')
const PROVIDER_NAMES = { openai: 'OpenAI', anthropic: 'Anthropic' } as const
const SOURCE_NAMES: Record<string, string> = {
  demo: 'Lokal DuckDB',
  local_export: 'Lokalt udtræk',
  databricks: 'SQL Warehouse',
}

export function Sidebar({ health, datasets, onNewChat, open, onClose }: Props) {
  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Datakilder">
      <div className="sidebar-head">
        <div className="brand">
          <span className="brand-mark" aria-hidden>MM</span>
          <div>
            <div className="brand-name">MealMind</div>
            <div className="brand-sub">AI Data Assistant</div>
          </div>
        </div>
        <button className="ghost-btn close-sidebar" onClick={onClose} type="button" aria-label="Luk">✕</button>
      </div>

      <button className="primary-btn" onClick={onNewChat} type="button">+ Ny samtale</button>

      <section className="side-section">
        <h2>Datakilde</h2>
        {health ? (
          <div className="source-line">
            <span className={`badge ${health.demo ? 'badge-demo' : 'badge-live'}`}>
              {sourceBadge(health)}
            </span>
            <span className="muted">{health.data_label ?? SOURCE_NAMES[health.data_source] ?? health.data_source}</span>
          </div>
        ) : (
          <div className="muted">Henter…</div>
        )}
      </section>

      <section className="side-section">
        <h2>Datasæt</h2>
        {datasets?.tables.map((t) => (
          <details key={t.name} className="dataset">
            <summary>
              <span className="dataset-name">{t.name.split('.').pop()}</span>
              {t.row_count != null && <span className="muted">{nf.format(t.row_count)} rækker</span>}
            </summary>
            {t.description && <p className="dataset-desc">{t.description}</p>}
            <ul className="columns">
              {t.columns.map((c) => (
                <li key={c.name} title={[c.description, c.sample_values.join(', ')].filter(Boolean).join(' · ')}>
                  <code>{c.name}</code>
                  <span className="muted">{c.type.toLowerCase()}</span>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </section>

      <section className="side-section">
        <h2>ML-funktioner</h2>
        <ul className="ml-list">
          {datasets?.ml_functions.map((f) => (
            <li key={f.name} title={f.description}><code>{f.name}</code></li>
          ))}
        </ul>
      </section>

      {health && <div className="sidebar-foot muted">Model: {health.model}{health.provider !== 'test' && ` (${PROVIDER_NAMES[health.provider]})`}</div>}
    </aside>
  )
}
