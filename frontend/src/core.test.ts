import { describe, expect, it } from 'vitest'
import { historyFor } from './api'
import { formatValue, sourceBadge, toCsv } from './format'
import { applyEvent } from './reducer'
import { createSseParser } from './sse'
import type { AgentEvent, AssistantMessage, Message } from './types'

const empty = (): AssistantMessage => ({ role: 'assistant', id: 'a', text: '', steps: [], visuals: [], status: 'streaming' })

describe('createSseParser', () => {
  it('samler events på tværs af chunks og ignorerer kommentarer', () => {
    const parse = createSseParser()
    expect(parse('data: {"a"')).toEqual([])
    expect(parse(':1}\n\n: ping\n\ndata: x\r\n\r\n')).toEqual(['{"a":1}', 'x'])
  })
})

describe('applyEvent', () => {
  it('bygger et komplet svar fra en eventsekvens', () => {
    const events: AgentEvent[] = [
      { type: 'start', demo: true, data_source: 'demo' },
      { type: 'step', id: 's1', tool: 'run_sql', input: { title: 'T' } },
      { type: 'sql', step_id: 's1', sql: 'SELECT 1', row_count: 3 },
      { type: 'step_done', id: 's1', ok: true, summary: '3 rækker' },
      { type: 'text_break' },
      { type: 'chart', step_id: 's2', chart: { type: 'bar', title: 'G', x: 'a', y: ['b'], stacked: false, data: [], notes: [] } },
      { type: 'text_delta', text: 'Hej ' },
      { type: 'text_delta', text: 'verden' },
      { type: 'done' },
    ]
    const msg = events.reduce(applyEvent, empty())
    expect(msg.demo).toBe(true)
    expect(msg.steps[0]).toMatchObject({ status: 'ok', sql: 'SELECT 1', rowCount: 3 })
    expect(msg.visuals).toHaveLength(1)
    expect(msg.text).toBe('Hej verden')
    expect(msg.status).toBe('done')
  })

  it('gemmer AIDA\'s plan og advarsler om ubekræftede tal', () => {
    const msg = [
      { type: 'plan', capabilities: ['sql', 'forecast'], labels: ['SQL', 'Prognose'], tools: ['run_sql', 'run_ml'],
        ml_functions: ['forecast_timeseries'], notes: [] },
      { type: 'notice', level: 'warning', message: 'Ubekræftede tal' },
      { type: 'done' },
    ].reduce((m, e) => applyEvent(m, e as AgentEvent), empty())
    expect(msg.plan).toEqual(['SQL', 'Prognose'])
    expect(msg.notices).toEqual(['Ubekræftede tal'])
    expect(msg.status).toBe('done')
  })

  it('markerer fejl', () => {
    const msg = applyEvent(empty(), { type: 'error', message: 'Ups' })
    expect(msg).toMatchObject({ status: 'error', error: 'Ups' })
  })
})

describe('sourceBadge', () => {
  it('viser aldrig syntetiske data som rigtige', () => {
    expect(sourceBadge({ demo: true, data_source: 'demo' })).toBe('DEMODATA')
    expect(sourceBadge({ demo: true, data_source: 'databricks' })).toBe('TESTDATA')
    expect(sourceBadge({ demo: false, data_source: 'databricks' })).toBe('Databricks')
    expect(sourceBadge({ demo: false, data_source: 'local_export' })).toBe('Udtræk')
  })
})

describe('historyFor', () => {
  it('sender kun brugerbeskeder og færdige svar', () => {
    const msgs: Message[] = [
      { role: 'user', id: '1', text: 'q1' },
      { ...empty(), id: '2', text: 'svar', status: 'done' },
      { role: 'user', id: '3', text: 'q2' },
      { ...empty(), id: '4', text: 'halvt', status: 'error' },
    ]
    expect(historyFor(msgs)).toEqual([
      { role: 'user', content: 'q1' },
      { role: 'assistant', content: 'svar' },
      { role: 'user', content: 'q2' },
    ])
  })
})

describe('format', () => {
  it('formaterer tal, datoer og tomme værdier', () => {
    expect(formatValue(null)).toBe('–')
    expect(formatValue('2026-03-01T00:00:00')).toBe('2026-03-01')
    expect(formatValue(true)).toBe('ja')
    expect(formatValue(1234.5)).toMatch(/1\.?234,5/)
  })
  it('escaper CSV', () => {
    expect(toCsv(['a', 'b'], [{ a: 'x,y', b: 'q"z' }])).toBe('a,b\n"x,y","q""z"')
  })
})
