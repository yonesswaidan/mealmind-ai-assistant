import { useMemo, useState } from 'react'
import { toCsv } from '../format'
import { columnLabel, displayValue } from '../present'
import type { TableSpec } from '../types'

export function DataTable({ spec }: { spec: TableSpec }) {
  const [sort, setSort] = useState<{ col: string; desc: boolean } | null>(null)

  const rows = useMemo(() => {
    if (!sort) return spec.rows
    const dir = sort.desc ? -1 : 1
    return [...spec.rows].sort((a, b) => {
      const av = a[sort.col], bv = b[sort.col]
      if (av === bv) return 0
      if (av === null) return 1
      if (bv === null) return -1
      return (av > bv ? 1 : -1) * dir
    })
  }, [spec.rows, sort])

  const numeric = useMemo(
    () => new Set(spec.columns.filter((c) => spec.rows.some((r) => typeof r[c] === 'number'))),
    [spec],
  )

  function download() {
    const blob = new Blob([toCsv(spec.columns, spec.rows)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${spec.title.replace(/[^\wæøåÆØÅ-]+/g, '_')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="card table-card" aria-label={spec.title}>
      <div className="card-head">
        <div className="card-title">{spec.title}</div>
        <button className="pill-btn" onClick={download} type="button">Hent CSV</button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {spec.columns.map((c) => (
                <th key={c} className={numeric.has(c) ? 'num' : undefined} title={c}>
                  <button type="button" onClick={() => setSort((s) => ({ col: c, desc: s?.col === c ? !s.desc : true }))}>
                    {columnLabel(c)}
                    {sort?.col === c && <span aria-hidden>{sort.desc ? ' ↓' : ' ↑'}</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {spec.columns.map((c) => (
                  <td key={c} className={numeric.has(c) ? 'num' : undefined}>{displayValue(r[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {spec.total_rows > spec.rows.length && (
        <div className="card-note">Viser {spec.rows.length} af {spec.total_rows} rækker.</div>
      )}
    </section>
  )
}
