import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getToken } from './api'
import { InsightsPanel } from './components/InsightsPanel'
import { MessageView } from './components/MessageView'
import { loadConversations, saveConversation } from './conversations'
import { conversationTitle, dataMode, MODE_TEXT, planLabel, tableToChart } from './insights'
import type { AssistantMessage, Message, Overview, TableSpec } from './types'

const table: TableSpec = {
  title: 'Sprungne måltider', result_id: 'r1', columns: ['meal_slot', 'skipped'], total_rows: 3, sql: 'SELECT 1',
  rows: [{ meal_slot: 'Morgenmad', skipped: 12 }, { meal_slot: 'Frokost', skipped: 7 }, { meal_slot: 'Aftensmad', skipped: 4 }],
}

const overview = (demo: boolean): Overview => ({
  data_source: demo ? 'demo' : 'databricks', data_label: demo ? 'DEMODATA' : 'Azure Databricks', demo,
  sources: [
    { table: 'meal_events', title: 'Måltider', kind: 'meals', rows: 1200, origin: demo ? 'demo' : 'real', description: '' },
    { table: 'shopping_food_items', title: 'Indkøb og køkkenskab', kind: 'shopping', rows: 300, origin: demo ? 'demo' : 'real', description: '' },
  ],
  quick_actions: [{ label: 'Find lignende retter', icon: 'dish', question: 'Hvilke retter ligner Linsesalat mest?' }],
  next_questions: ['Hvilke varer udløber snart?'],
  ml_status: [{ name: 'meal_similarity', title: 'Lignende retter', status: 'trained', label: demo ? 'Demo' : 'Klar', detail: '', source: 'databricks' }],
})

describe('datatilstand', () => {
  it('viser aldrig syntetiske data som rigtige', () => {
    expect(dataMode({ demo: true, data_source: 'demo' })).toBe('demo')
    expect(dataMode({ demo: true, data_source: 'databricks' })).toBe('test')
    expect(dataMode({ demo: false, data_source: 'databricks' })).toBe('real')
    expect(dataMode(null)).toBeNull()
    expect(MODE_TEXT.demo.badge).toBe('Demotilstand')
    expect(MODE_TEXT.real.footer).toContain('Pseudonymiserede')
  })
})

describe('hjælpefunktioner', () => {
  it('formulerer analysetypen', () => {
    expect(planLabel(['SQL', 'Statistik'])).toBe('Analyse: Statistik')
    expect(planLabel(['SQL'])).toBe('Analyse: SQL')
    expect(planLabel(['SQL', 'Prognose', 'Visualisering'])).toBe('Analyse: Prognose · Visualisering')
    expect(planLabel(undefined)).toBeNull()
  })

  it('laver en søjlegraf af en tabel med tekst og tal', () => {
    const chart = tableToChart(table)!
    expect(chart.type).toBe('bar')
    expect(chart.x).toBe('meal_slot')
    expect(chart.y).toEqual(['skipped'])
    expect(tableToChart({ ...table, columns: ['meal_slot'], rows: table.rows.map((r) => ({ meal_slot: r.meal_slot })) })).toBeNull()
  })

  it('giver samtaler en kort titel', () => {
    expect(conversationTitle([{ role: 'user', id: 'u', text: 'Hvilke måltider bliver oftest sprunget over?' }]))
      .toBe('Hvilke måltider bliver oftest sprunget over?')
    expect(conversationTitle([])).toBe('Ny samtale')
  })
})

describe('seneste samtaler', () => {
  beforeEach(() => localStorage.clear())

  it('gemmer, opdaterer og begrænser samtaler', () => {
    const msgs: Message[] = [{ role: 'user', id: 'u1', text: 'Spørgsmål 1' }]
    saveConversation('c1', msgs, 1)
    saveConversation('c2', [{ role: 'user', id: 'u2', text: 'Spørgsmål 2' }], 2)
    saveConversation('c1', [...msgs, { role: 'user', id: 'u3', text: 'Opfølgning' }], 3)
    const list = loadConversations()
    expect(list.map((c) => c.id)).toEqual(['c1', 'c2'])
    expect(list[0].messages).toHaveLength(2)
    for (let i = 0; i < 20; i++) saveConversation(`x${i}`, msgs, 10 + i)
    expect(loadConversations()).toHaveLength(12)
  })

  it('tåler blokeret storage', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blokeret') })
    expect(() => saveConversation('c', [{ role: 'user', id: 'u', text: 'x' }])).not.toThrow()
    spy.mockRestore()
  })
})

describe('adgangstoken', () => {
  beforeEach(() => localStorage.clear())

  it('flytter et token gemt under det gamle navn', () => {
    localStorage.setItem('mealmind-assistant-token', 'gammel')
    expect(getToken()).toBe('gammel')
    expect(localStorage.getItem('mealmind-insights-token')).toBe('gammel')
    expect(localStorage.getItem('mealmind-assistant-token')).toBeNull()
  })
})

describe('brugerflade', () => {
  it('panelet viser demodata tydeligt og sender næste spørgsmål', () => {
    const onAsk = vi.fn()
    render(<InsightsPanel overview={overview(true)} mode="demo" questions={['Hvilke varer udløber snart?']} onAsk={onAsk}
      onOpenSource={() => {}} busy={false} />)
    expect(screen.getAllByText('Demodata')).toHaveLength(2)
    expect(screen.getByText('Måltider')).toBeInTheDocument()
    expect(screen.getByText('Demo')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Hvilke varer udløber snart?'))
    expect(onAsk).toHaveBeenCalledWith('Hvilke varer udløber snart?')
  })

  it('panelet viser rigtige data', () => {
    render(<InsightsPanel overview={overview(false)} mode="real" questions={[]} onAsk={() => {}} onOpenSource={() => {}} busy={false} />)
    expect(screen.getAllByText('Rigtige data')).toHaveLength(2)
    expect(screen.getByText('Klar')).toBeInTheDocument()
  })

  it('svarkortet viser analysetype, datagrundlag og kan vise tabellen som graf', () => {
    const msg: AssistantMessage = {
      role: 'assistant', id: 'a', text: 'Morgenmad bliver oftest sprunget over.', status: 'done', demo: true,
      plan: ['SQL', 'Statistik'],
      steps: [{ id: 's1', tool: 'run_sql', input: { title: 'Sprungne måltider' }, status: 'ok', sql: 'SELECT meal_slot FROM meal_events', rowCount: 3 }],
      visuals: [{ kind: 'table', id: 't1', table }],
    }
    render(<MessageView msg={msg} mode="demo" />)
    expect(screen.getByText('Analyse: Statistik')).toBeInTheDocument()
    expect(screen.getByText('Baseret på demodata')).toBeInTheDocument()
    expect(screen.queryByText('SELECT meal_slot FROM meal_events')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Se datagrundlag/ }))
    expect(screen.getByText('SELECT meal_slot FROM meal_events')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Vis som graf/ }))
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByRole('figure', { name: 'Sprungne måltider' })).toBeInTheDocument()
  })
})
