import { useState } from 'react'
import { EXPIRY_COL, columnLabel, displayName, expiryFor, foodEmoji, toStats, valueWithUnit } from '../present'
import type { TableSpec } from '../types'
import { DataTable } from './DataTable'
import { IconDish } from './Icons'

const MAX_CARDS = 12

/** Konkrete varer, retter eller ingredienser som kort - første tekstkolonne er navnet. */
export function ItemCards({ spec }: { spec: TableSpec }) {
  const [asTable, setAsTable] = useState(false)
  const nameCol = spec.columns.find((c) => spec.rows.some((r) => typeof r[c] === 'string')) ?? spec.columns[0]
  const details = spec.columns.filter((c) => c !== nameCol && !/(^|_)(id|key)$/i.test(c))
  const total = Math.max(spec.total_rows, spec.rows.length)

  if (asTable || !nameCol) {
    return (
      <div className="result-block">
        <DataTable spec={spec} />
        <button type="button" className="link-btn" onClick={() => setAsTable(false)}>Vis som kort</button>
      </div>
    )
  }

  return (
    <section className="result-block" aria-label={spec.title}>
      <div className="result-head">
        <h3 className="result-title">{spec.title}</h3>
        <button type="button" className="pill-btn" onClick={() => setAsTable(true)}>
          {total > MAX_CARDS ? `Se alle ${total}` : 'Se som tabel'}
        </button>
      </div>
      <ul className="item-grid">
        {spec.rows.slice(0, MAX_CARDS).map((row, i) => {
          const name = displayName(row[nameCol])
          const emoji = foodEmoji(name)
          const expiry = expiryFor(row, spec.columns)
          const shown = details.filter((c) => !(expiry && (EXPIRY_COL.test(c) || /days|dage/i.test(c)))).slice(0, 2)
          return (
            <li key={i} className="item-card">
              <span className="item-visual" aria-hidden>{emoji ?? <IconDish size={22} />}</span>
              <span className="item-text">
                <span className="item-name" title={name}>{name}</span>
                {expiry && (
                  <span className={`item-status status-${expiry.level}`}>
                    <span className="dot" aria-hidden /> {expiry.text}
                  </span>
                )}
                {shown.map((c) => (
                  <span key={c} className="item-detail">
                    <span className="muted">{columnLabel(c)}:</span> {valueWithUnit(row[c], c)}
                  </span>
                ))}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function StatCards({ spec }: { spec: TableSpec }) {
  const stats = toStats(spec)
  if (stats.length === 0) return <DataTable spec={spec} />
  return (
    <section className="result-block" aria-label={spec.title}>
      <h3 className="result-title">{spec.title}</h3>
      <ul className="stat-grid">
        {stats.map((s) => (
          <li key={s.label} className="stat-card">
            <span className="stat-label">{s.label}</span>
            <span className="stat-value">{s.value}</span>
            {s.extra.map((e) => <span key={e} className="stat-extra">{e}</span>)}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Vælger visning ud fra AI'ens display-valg; tabellen er altid fallback. */
export function TableResult({ spec }: { spec: TableSpec }) {
  if (spec.display === 'cards' && spec.rows.length > 0) return <ItemCards spec={spec} />
  if (spec.display === 'stats' && spec.rows.length > 0) return <StatCards spec={spec} />
  return <DataTable spec={spec} />
}
