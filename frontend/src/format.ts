import type { Cell } from './types'

const nf = new Intl.NumberFormat('da-DK', { maximumFractionDigits: 2 })
const compact = new Intl.NumberFormat('da-DK', { notation: 'compact', maximumFractionDigits: 1 })

export function isDateLike(v: string): boolean {
  return /^\d{4}-\d{2}-\d{2}(T|$)/.test(v)
}

export function formatValue(v: Cell | undefined, short = false): string {
  if (v === null || v === undefined) return '–'
  if (typeof v === 'number') return short && Math.abs(v) >= 1_000_000 ? compact.format(v) : nf.format(v)
  if (typeof v === 'boolean') return v ? 'ja' : 'nej'
  if (isDateLike(v)) return v.endsWith('T00:00:00') ? v.slice(0, 10) : v.replace('T', ' ').slice(0, 16)
  return v
}

export function toCsv(columns: string[], rows: Record<string, Cell>[]): string {
  const esc = (v: Cell) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  return [columns.map(esc).join(','), ...rows.map((r) => columns.map((c) => esc(r[c])).join(','))].join('\n')
}

/** Mærkat for datakilden. Syntetiske data (demo eller testkatalog) vises aldrig som rigtige data. */
export function sourceBadge(health: { demo: boolean; data_source: string }): string {
  if (health.demo) return health.data_source === 'demo' ? 'DEMODATA' : 'TESTDATA'
  if (health.data_source === 'databricks') return 'Databricks'
  return health.data_source === 'local_lakehouse' ? 'Lokalt' : 'Udtræk'
}
