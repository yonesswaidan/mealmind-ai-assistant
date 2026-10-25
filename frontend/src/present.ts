import { formatValue, isDateLike } from './format'
import type { Cell, ChartSpec, MlStatus, Overview, QuickAction, TableSpec } from './types'

/** Brugervenlige danske navne for kolonner, som AI'en typisk henter. Ukendte kolonner gøres læsbare automatisk. */
const LABELS: Record<string, string> = {
  meal_slot: 'Måltidstype',
  meal_type: 'Måltidstype',
  meal_name: 'Ret',
  item_name: 'Vare',
  name: 'Navn',
  category: 'Kategori',
  status: 'Status',
  city: 'By',
  calories: 'Kalorier',
  calories_kcal: 'Kalorier',
  avg_calories: 'Gns. kalorier',
  avg_calories_kcal: 'Gns. kalorier',
  avg_kcal: 'Gns. kalorier',
  expiry_date: 'Udløbsdato',
  expiry_status: 'Holdbarhed',
  days_until_expiry: 'Dage til udløb',
  days_left: 'Dage tilbage',
  quantity: 'Mængde',
  quantity_text: 'Mængde',
  amount: 'Mængde',
  unit: 'Enhed',
  first_expiry: 'Første udløb',
  earliest_expiry: 'Tidligste udløb',
  price_dkk: 'Pris (kr.)',
  event_date: 'Dato',
  date: 'Dato',
  day: 'Dag',
  week: 'Uge',
  month: 'Måned',
  n: 'Antal',
  count: 'Antal',
  rows: 'Antal',
  meals: 'Måltider',
  skipped: 'Sprunget over',
  skip_rate: 'Andel sprunget over',
  share: 'Andel',
  users: 'Brugere',
  user_key: 'Bruger',
  similarity: 'Lighed',
  score: 'Score',
  forecast: 'Prognose',
  actual: 'Faktisk',
}

export function columnLabel(col: string): string {
  const known = LABELS[col.toLowerCase()]
  if (known) return known
  // AI'en skriver ofte danske aliaser uden æøå i SQL (maaltidstype, tidligste_udloeb).
  const words = col.replace(/[_-]+/g, ' ').trim()
    .replace(/aa/g, 'å').replace(/oe/g, 'ø').replace(/ae/g, 'æ')
    .replace(/\s(pct|procent)$/i, ' (%)')
  return words ? words[0].toUpperCase() + words.slice(1) : col
}

/** Danske visningsnavne for kendte kodeværdier fra MealMind (måltidstyper og status). Kun visning - data er uændret. */
const VALUE_LABELS: Record<string, string> = {
  breakfast: 'Morgenmad', lunch: 'Frokost', dinner: 'Aftensmad', snack: 'Snack', snacks: 'Snacks',
  skipped: 'Sprunget over', eaten: 'Spist', planned: 'Planlagt', logged: 'Logget', cooked: 'Lavet',
}

export function displayValue(v: Cell | undefined): string {
  if (typeof v === 'string') {
    const label = VALUE_LABELS[v.toLowerCase()]
    if (label) return label
  }
  return formatValue(v)
}

/** Navn på et kort: første bogstav stort, resten som i data. */
export function displayName(v: Cell | undefined): string {
  const s = displayValue(v)
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

/** Enhed ud fra kolonnenavnet - kun hvor navnet siger det entydigt. */
export function unitFor(col: string): string {
  const c = col.toLowerCase()
  if (/kcal|calorie|kalori/.test(c)) return 'kcal'
  if (/(_pct|percent|procent)$/.test(c)) return '%'
  if (/(_dkk|price|pris)/.test(c)) return 'kr.'
  if (/(_g|_gram|gram)$/.test(c)) return 'g'
  return ''
}

const DAY_MS = 86_400_000
/** Kolonner om udløb/holdbarhed - også danske aliaser skrevet uden ø. */
export const EXPIRY_COL = /expir|udl(ø|oe|o)b|best_before|holdbar/i

/** Hele dage fra i dag til en dato (negativ = overskredet). Datoer sammenlignes som kalenderdage. */
export function daysUntil(value: string, today = new Date()): number | null {
  if (!isDateLike(value)) return null
  const [y, m, d] = value.slice(0, 10).split('-').map(Number)
  const target = Date.UTC(y, m - 1, d)
  const base = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((target - base) / DAY_MS)
}

export interface Expiry {
  days: number
  text: string
  level: 'soon' | 'near' | 'later' | 'past'
}

function expiryText(days: number): Expiry {
  if (days < 0) return { days, text: `Udløbet for ${-days} ${-days === 1 ? 'dag' : 'dage'} siden`, level: 'past' }
  const text = days === 0 ? 'Udløber i dag' : days === 1 ? 'Udløber i morgen' : `Udløber om ${days} dage`
  return { days, text, level: days <= 2 ? 'soon' : days <= 4 ? 'near' : 'later' }
}

/** Finder udløb i en række: en dato-kolonne om udløb/holdbarhed eller en kolonne med dage til udløb. */
export function expiryFor(row: Record<string, Cell>, columns: string[], today = new Date()): Expiry | null {
  const daysCol = columns.find((c) => /days.*(expir|left|until)|dage.*(udl|tilbage)/i.test(c) && typeof row[c] === 'number')
  if (daysCol) return expiryText(Math.round(row[daysCol] as number))
  const dateCol = columns.find((c) => EXPIRY_COL.test(c) && typeof row[c] === 'string')
  const days = dateCol ? daysUntil(row[dateCol] as string, today) : null
  return days === null ? null : expiryText(days)
}

/** Emoji for kendte fødevarer og retter - ren pynt, der aldrig ændrer data. */
const FOOD: [RegExp, string][] = [
  [/broccoli/i, '🥦'], [/yoghurt|skyr|ymer/i, '🥛'], [/mælk|milk/i, '🥛'], [/kylling|chicken/i, '🍗'],
  [/tomat|tomato/i, '🍅'], [/æg\b|egg/i, '🥚'], [/brød|bread|rugbrød|bolle/i, '🍞'], [/ost\b|cheese|feta|mozzarella/i, '🧀'],
  [/æble|apple/i, '🍎'], [/banan/i, '🍌'], [/gulerod|gulerød|carrot/i, '🥕'], [/kartof|potato/i, '🥔'],
  [/løg|onion/i, '🧅'], [/hvidløg|garlic/i, '🧄'], [/laks|fisk|torsk|tun|salmon|fish/i, '🐟'], [/rejer|shrimp/i, '🦐'],
  [/ris\b|rice/i, '🍚'], [/pasta|spaghetti|lasagne/i, '🍝'], [/salat|salad/i, '🥗'], [/suppe|soup/i, '🍲'],
  [/oksekød|hakket|beef|bøf|burger/i, '🥩'], [/svin|bacon|pork|skinke/i, '🥓'], [/pizza/i, '🍕'], [/avocado/i, '🥑'],
  [/agurk|cucumber/i, '🥒'], [/peber|pepper/i, '🫑'], [/svamp|champignon|mushroom/i, '🍄'], [/citron|lemon/i, '🍋'],
  [/jordbær|strawberr/i, '🍓'], [/bær|berr/i, '🫐'], [/appelsin|orange/i, '🍊'], [/smør|butter/i, '🧈'],
  [/havre|grød|müsli|granola|oat/i, '🥣'], [/linse|bønne|kikært|lentil|bean/i, '🫘'], [/majs|corn/i, '🌽'],
  [/sandwich|toast/i, '🥪'], [/wrap|taco|burrito/i, '🌯'], [/kage|cake/i, '🍰'], [/kaffe|coffee/i, '☕'],
]

export function foodEmoji(name: string): string | null {
  return FOOD.find(([re]) => re.test(name))?.[1] ?? null
}

export interface Suggestion {
  label: string
  question: string
  icon: 'dish' | 'chart' | 'users' | 'search'
}

function iconFor(q: string): Suggestion['icon'] {
  if (/udløb|vare|indkøb|ret(ter)?\b|ligner/i.test(q)) return 'dish'
  if (/kalori|bruger|segment|fordel/i.test(q)) return 'users'
  if (/afvig|usædvanlig/i.test(q)) return 'search'
  return 'chart'
}

/**
 * Forslag til forsiden: konkrete spørgsmål, som datakilden kan besvare (fra /api/overview), suppleret med de
 * hurtige handlinger. Intet er hardcodet - findes en kolonne ikke, foreslås spørgsmålet heller ikke.
 */
export function suggestionsFrom(overview: Overview | null, max = 3): Suggestion[] {
  if (!overview) return []
  const out: Suggestion[] = overview.next_questions.map((q) => ({ label: q, question: q, icon: iconFor(q) }))
  for (const a of overview.quick_actions) out.push(quickToSuggestion(a))
  const seen = new Set<string>()
  return out.filter((s) => !seen.has(s.question) && seen.add(s.question)).slice(0, max)
}

function quickToSuggestion(a: QuickAction): Suggestion {
  return { label: a.label, question: a.question, icon: a.icon === 'search' ? 'search' : a.icon === 'dish' ? 'dish' : 'chart' }
}

export interface AnswerParts {
  body: string
  insight: string | null
  suggestions: string | null
}

const SECTION = /^\s{0,3}(?:#{1,4}\s*|\*\*)\s*(Vigtig indsigt|Forslag til MealMind|Forslag)\s*:?\s*(?:\*\*)?\s*:?\s*$/gim

/** Deler svaret i brødtekst og de valgfri sektioner "Vigtig indsigt" og "Forslag til MealMind". */
export function splitAnswer(text: string): AnswerParts {
  const marks = [...text.matchAll(SECTION)].map((m) => ({ at: m.index ?? 0, end: (m.index ?? 0) + m[0].length, name: m[1].toLowerCase() }))
  if (marks.length === 0) return { body: text, insight: null, suggestions: null }
  const parts: AnswerParts = { body: text.slice(0, marks[0].at).trim(), insight: null, suggestions: null }
  marks.forEach((m, i) => {
    const content = text.slice(m.end, marks[i + 1]?.at ?? text.length).trim()
    if (!content) return
    if (m.name.startsWith('vigtig')) parts.insight = parts.insight ? `${parts.insight}\n\n${content}` : content
    else parts.suggestions = parts.suggestions ? `${parts.suggestions}\n\n${content}` : content
  })
  return parts
}

const timeFmt = new Intl.DateTimeFormat('da-DK', { hour: '2-digit', minute: '2-digit' })
const dateFmt = new Intl.DateTimeFormat('da-DK', { day: 'numeric', month: 'short' })

export function formatTime(ts: number, now = new Date()): string {
  const d = new Date(ts)
  const sameDay = d.toDateString() === now.toDateString()
  return `${sameDay ? 'i dag' : dateFmt.format(d)} kl. ${timeFmt.format(d)}`
}

const isNumber = (v: Cell | undefined): v is number => typeof v === 'number'

export function valueWithUnit(v: Cell | undefined, col: string): string {
  const unit = isNumber(v) ? unitFor(col) : ''
  return unit ? `${formatValue(v)} ${unit}` : formatValue(v)
}

export interface Stat {
  label: string
  value: string
  extra: string[]
}

/** Nøgletal: én række med talkolonner (ét kort pr. kolonne) eller rækker med navn + tal (ét kort pr. række). */
export function toStats(spec: TableSpec): Stat[] {
  const numeric = spec.columns.filter((c) => spec.rows.some((r) => isNumber(r[c])))
  if (numeric.length === 0) return []
  if (spec.rows.length === 1) {
    const row = spec.rows[0]
    return numeric.map((c) => ({ label: columnLabel(c), value: valueWithUnit(row[c], c), extra: [] }))
  }
  const labelCol = spec.columns.find((c) => !numeric.includes(c))
  const [main, ...rest] = numeric
  return spec.rows.map((r, i) => ({
    label: labelCol ? displayValue(r[labelCol]) : `#${i + 1}`,
    value: valueWithUnit(r[main], main),
    extra: rest.slice(0, 2).map((c) => `${columnLabel(c)}: ${valueWithUnit(r[c], c)}`),
  }))
}

const COMPACT_MAX = 6

/** Få kategorier med én serie (fx kalorier pr. måltidstype) vises som kompakte søjler med værdien over. */
export function isCompact(spec: ChartSpec): boolean {
  if (spec.type !== 'bar' || spec.stacked || spec.y.length !== 1) return false
  if (spec.data.length < 2 || spec.data.length > COMPACT_MAX) return false
  const key = spec.y[0]
  return spec.data.every((r) => typeof r[key] === 'number' && (r[key] as number) >= 0
    && !(typeof r[spec.x] === 'string' && isDateLike(r[spec.x] as string)))
}

/**
 * Status vist for modellen. "Demo" vises ikke som mærkat ved hver model - datagrundlaget står ét sted i
 * brugerfladen - men en model på syntetiske data kaldes aldrig "Klar" (kun production_ready giver "Klar").
 */
export function mlLabel(m: MlStatus): string {
  if (m.label !== 'Demo') return m.label
  return m.status === 'trained' ? 'Trænet' : 'På forespørgsel'
}

