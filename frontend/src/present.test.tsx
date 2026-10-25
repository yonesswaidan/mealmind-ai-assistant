import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChartView } from './components/ChartView'
import { ItemCards, TableResult } from './components/ResultCards'
import { columnLabel, daysUntil, displayValue, expiryFor, foodEmoji, formatTime, isCompact, splitAnswer, suggestionsFrom, toStats, unitFor } from './present'
import type { ChartSpec, Overview, TableSpec } from './types'

const today = new Date(2026, 9, 25)

describe('splitAnswer', () => {
  it('deler svaret i brødtekst, indsigt og forslag', () => {
    const parts = splitAnswer('Konklusion.\n\n## Vigtig indsigt\nAftensmad fylder mest.\n\n**Forslag til MealMind**\n- Idé')
    expect(parts).toEqual({ body: 'Konklusion.', insight: 'Aftensmad fylder mest.', suggestions: '- Idé' })
  })
  it('lader svar uden sektioner være uændrede', () => {
    expect(splitAnswer('Bare tekst')).toEqual({ body: 'Bare tekst', insight: null, suggestions: null })
  })
  it('ignorerer tomme sektioner', () => {
    expect(splitAnswer('Tekst\n### Vigtig indsigt\n').insight).toBeNull()
  })
})

describe('udløb', () => {
  it('beregner dage ud fra en udløbsdato i data', () => {
    expect(daysUntil('2026-10-27', today)).toBe(2)
    expect(daysUntil('2026-10-25T00:00:00', today)).toBe(0)
    expect(daysUntil('ikke en dato', today)).toBeNull()
    const cols = ['item_name', 'expiry_date']
    expect(expiryFor({ item_name: 'Broccoli', expiry_date: '2026-10-27' }, cols, today)).toMatchObject({ text: 'Udløber om 2 dage', level: 'soon' })
    expect(expiryFor({ item_name: 'Ost', expiry_date: '2026-10-29' }, cols, today)).toMatchObject({ level: 'near' })
    expect(expiryFor({ item_name: 'Ris', expiry_date: '2026-10-24' }, cols, today)?.text).toBe('Udløbet for 1 dag siden')
    expect(expiryFor({ item_name: 'Æg', days_until_expiry: 1 }, ['item_name', 'days_until_expiry'], today)?.text).toBe('Udløber i morgen')
    expect(expiryFor({ item_name: 'Æg', category: 'Mejeri' }, ['item_name', 'category'], today)).toBeNull()
  })
})

describe('tekster', () => {
  it('giver kolonner danske navne og enheder', () => {
    expect(columnLabel('meal_slot')).toBe('Måltidstype')
    expect(columnLabel('avg_protein_g')).toBe('Avg protein g')
    expect(unitFor('avg_calories_kcal')).toBe('kcal')
    expect(unitFor('meal_slot')).toBe('')
    expect(foodEmoji('Kyllingebryst')).toBe('🍗')
    expect(foodEmoji('Ukendt vare')).toBeNull()
  })
  it('læser danske aliaser uden æøå og oversætter kendte kodeværdier', () => {
    expect(columnLabel('maaltidstype')).toBe('Måltidstype')
    expect(columnLabel('tidligste_udloeb')).toBe('Tidligste udløb')
    expect(columnLabel('oversprunget_pct')).toBe('Oversprunget (%)')
    expect(displayValue('dinner')).toBe('Aftensmad')
    expect(displayValue('Linsesalat')).toBe('Linsesalat')
    expect(expiryFor({ vare: 'tomat', tidligste_udloeb: '2026-10-26' }, ['vare', 'tidligste_udloeb'], today)?.text).toBe('Udløber i morgen')
  })
  it('viser tidspunkt for svar', () => {
    expect(formatTime(new Date(2026, 9, 25, 10, 24).getTime(), today)).toMatch(/^i dag kl\. 10[.:]24$/)
    expect(formatTime(new Date(2026, 9, 20, 9, 5).getTime(), today)).toMatch(/^20\. okt\.? kl\. 09[.:]05$/)
  })
})

describe('forslag', () => {
  const ov = {
    next_questions: ['Hvilke varer udløber snart?', 'Hvilke måltider bliver oftest sprunget over?'],
    quick_actions: [{ label: 'Vis ugens overblik', icon: 'chart', question: 'Giv mig et overblik.' },
      { label: 'Find afvigelser', icon: 'search', question: 'Var der afvigelser?' }],
  } as unknown as Overview
  it('bruger datakildens egne forslag og fylder op med hurtige handlinger', () => {
    const s = suggestionsFrom(ov)
    expect(s.map((x) => x.label)).toEqual(['Hvilke varer udløber snart?', 'Hvilke måltider bliver oftest sprunget over?', 'Vis ugens overblik'])
    expect(s[0].icon).toBe('dish')
    expect(suggestionsFrom(null)).toEqual([])
  })
})

const items: TableSpec = {
  title: 'Varer der udløber snart', result_id: 'r1', columns: ['item_name', 'category', 'expiry_date'], total_rows: 2,
  display: 'cards',
  rows: [{ item_name: 'Broccoli', category: 'Grønt', expiry_date: '2099-01-01' }, { item_name: 'Yoghurt naturel', category: 'Mejeri', expiry_date: null }],
}

describe('resultatkort', () => {
  it('viser varer som kort med data fra forespørgslen og kan skifte til tabel', () => {
    render(<ItemCards spec={items} />)
    expect(screen.getByText('Broccoli')).toBeInTheDocument()
    expect(screen.getByText('🥦')).toBeInTheDocument()
    expect(screen.getAllByText(/Udløber om/)).toHaveLength(1)
    expect(screen.getByText('Mejeri')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Se som tabel' }))
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('laver nøgletal af én række eller af rækker med navn og tal', () => {
    const one: TableSpec = { title: 'T', result_id: 'r', columns: ['meals', 'avg_calories_kcal'], rows: [{ meals: 1200, avg_calories_kcal: 512.5 }], total_rows: 1 }
    expect(toStats(one).map((s) => [s.label, s.value])).toEqual([['Måltider', '1.200'], ['Gns. kalorier', '512,5 kcal']])
    const many: TableSpec = { title: 'T', result_id: 'r', columns: ['meal_slot', 'calories_kcal'], total_rows: 2,
      rows: [{ meal_slot: 'Frokost', calories_kcal: 531 }, { meal_slot: 'Aftensmad', calories_kcal: 620 }] }
    expect(toStats(many).map((s) => s.value)).toEqual(['531 kcal', '620 kcal'])
    render(<TableResult spec={{ ...many, display: 'stats' }} />)
    expect(screen.getByText('Aftensmad')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('falder tilbage til tabel uden display-valg', () => {
    render(<TableResult spec={{ ...items, display: undefined }} />)
    expect(screen.getByRole('table')).toBeInTheDocument()
  })
})

describe('kompakte søjler', () => {
  const spec: ChartSpec = {
    type: 'bar', title: 'Kalorier pr. måltidstype', x: 'meal_slot', y: ['avg_calories_kcal'], stacked: false, notes: [],
    data: [{ meal_slot: 'Morgenmad', avg_calories_kcal: 412 }, { meal_slot: 'Aftensmad', avg_calories_kcal: 620 }],
  }
  it('viser få kategorier med værdi og enhed over hver søjle', () => {
    expect(isCompact(spec)).toBe(true)
    expect(isCompact({ ...spec, y: ['a', 'b'] })).toBe(false)
    expect(isCompact({ ...spec, data: [{ meal_slot: '2026-01-01', avg_calories_kcal: 1 }, { meal_slot: '2026-01-02', avg_calories_kcal: 2 }] })).toBe(false)
    render(<ChartView spec={spec} />)
    expect(screen.getByRole('figure', { name: 'Kalorier pr. måltidstype' })).toBeInTheDocument()
    expect(screen.getByText('620 kcal')).toBeInTheDocument()
  })
})
