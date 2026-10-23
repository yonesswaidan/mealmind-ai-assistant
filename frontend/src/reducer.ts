import type { AgentEvent, AssistantMessage, Step } from './types'

function updateStep(msg: AssistantMessage, id: string, patch: Partial<Step>): AssistantMessage {
  return { ...msg, steps: msg.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) }
}

/** Anvender ét agent-event på det assistentsvar, der er ved at blive streamet. */
export function applyEvent(msg: AssistantMessage, ev: AgentEvent): AssistantMessage {
  switch (ev.type) {
    case 'start':
      return { ...msg, demo: ev.demo }
    case 'text_delta':
      return { ...msg, text: msg.text + ev.text }
    case 'text_break':
      return msg.text && !msg.text.endsWith('\n\n') ? { ...msg, text: msg.text + '\n\n' } : msg
    case 'step':
      return { ...msg, steps: [...msg.steps, { id: ev.id, tool: ev.tool, input: ev.input, status: 'running' }] }
    case 'sql':
      return updateStep(msg, ev.step_id, { sql: ev.sql, rowCount: ev.row_count })
    case 'ml':
      return updateStep(msg, ev.step_id, { ml: { function: ev.function, summary: ev.summary } })
    case 'chart':
      return { ...msg, visuals: [...msg.visuals, { kind: 'chart', id: `${ev.step_id}-c${msg.visuals.length}`, chart: ev.chart }] }
    case 'table':
      return { ...msg, visuals: [...msg.visuals, { kind: 'table', id: `${ev.step_id}-t${msg.visuals.length}`, table: ev.table }] }
    case 'step_done':
      return updateStep(msg, ev.id, { status: ev.ok ? 'ok' : 'error', summary: ev.summary })
    case 'done':
      return { ...msg, status: 'done', text: msg.text.trim() }
    case 'error':
      return { ...msg, status: 'error', error: ev.message, text: msg.text.trim() }
    default:
      return msg
  }
}
