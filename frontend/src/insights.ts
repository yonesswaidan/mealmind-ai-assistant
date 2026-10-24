import type { AssistantMessage, Cell, ChartSpec, Health, Message, TableSpec } from './types'

/** Datatilstand som brugeren ser den. Syntetiske data vises aldrig som rigtige data. */
export type DataMode = 'demo' | 'test' | 'real'

export function dataMode(health: Pick<Health, 'demo' | 'data_source'> | null): DataMode | null {
  if (!health) return null
  if (health.demo) return health.data_source === 'demo' ? 'demo' : 'test'
  return 'real'
}

export const MODE_TEXT: Record<DataMode, { badge: string; origin: string; footer: string }> = {
  demo: {
    badge: 'Demotilstand',
    origin: 'Demodata',
    footer: 'Eksempelvisning · Syntetiske demodata · Ingen produktionsdata',
  },
  test: {
    badge: 'Testdata',
    origin: 'Testdata',
    footer: 'Syntetiske testdata fra MealMind-pipelinen · Ingen produktionsdata',
  },
  real: {
    badge: 'Rigtige data',
    origin: 'Rigtige data',
    footer: 'Pseudonymiserede MealMind-data · Kun læseadgang',
  },
}

/** Hvor analysen er kørt - lokalt beregnede data må aldrig ligne en Azure Databricks-kørsel. */
export function executionNote(health: Pick<Health, 'data_source' | 'execution_environment'> | null): string {
  if (!health) return ''
  if (health.execution_environment === 'databricks' || health.data_source === 'databricks') return 'Azure Databricks'
  return health.data_source === 'local_lakehouse' ? 'Beregnet lokalt · ikke Azure Databricks' : 'Beregnet lokalt'
}

/** "Analyse: Prognose · Visualisering" - SQL nævnes kun, når det er det eneste værktøj. */
export function planLabel(labels: string[] | undefined): string | null {
  if (!labels || labels.length === 0) return null
  const rest = labels.filter((l) => l !== 'SQL')
  return `Analyse: ${(rest.length ? rest : labels).join(' · ')}`
}

/** Laver en søjlegraf af en tabel, når den har en tekst-/datokolonne og mindst én talkolonne. */
export function tableToChart(table: TableSpec): ChartSpec | null {
  if (table.rows.length < 2) return null
  const isNum = (c: string) => table.rows.every((r) => r[c] === null || typeof r[c] === 'number')
    && table.rows.some((r) => typeof r[c] === 'number')
  const numeric = table.columns.filter(isNum)
  const x = table.columns.find((c) => !numeric.includes(c))
  if (!x || numeric.length === 0) return null
  const y = numeric.slice(0, 3)
  const data: Record<string, Cell>[] = table.rows.slice(0, 40).map((r) => ({ [x]: r[x], ...Object.fromEntries(y.map((c) => [c, r[c]])) }))
  return { type: 'bar', title: table.title, x, y, stacked: false, data, notes: table.rows.length > 40 ? ['Viser de første 40 rækker.'] : [] }
}

export function hasChartFor(msg: AssistantMessage, table: TableSpec): boolean {
  return msg.visuals.some((v) => v.kind === 'chart' && v.chart.title === table.title)
}

export function conversationTitle(messages: Message[]): string {
  const first = messages.find((m) => m.role === 'user')
  if (!first) return 'Ny samtale'
  const t = first.text.trim().replace(/\s+/g, ' ')
  return t.length > 48 ? `${t.slice(0, 47)}…` : t
}

export const nf = new Intl.NumberFormat('da-DK')
